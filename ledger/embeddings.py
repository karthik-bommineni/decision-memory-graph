"""Embeddings via OpenRouter (OpenAI-compatible). Default: openai/text-embedding-3-small, 1536-d."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from functools import lru_cache

import numpy as np

from ledger.config import CACHE_DIR, embed_base_url, embed_model, openrouter_key

DIM = 1536
MAX_BATCH = 64
# text-embedding-3-small rejects inputs over 8192 tokens. Dense code/SQL
# can be ~2-3 chars/token, so keep a conservative character cap.
MAX_EMBED_CHARS = 16000

_CACHE = CACHE_DIR / "embed_cache.sqlite"


def _model_name() -> str:
    return embed_model()


def _clip_for_embed(text: str) -> str:
    text = text if text.strip() else " "
    if len(text) <= MAX_EMBED_CHARS:
        return text
    return text[:MAX_EMBED_CHARS]


def _cache() -> sqlite3.Connection:
    conn = sqlite3.connect(_CACHE)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS embeddings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    return conn


def _cache_key(text: str) -> str:
    return hashlib.sha256(f"{_model_name()}\n{text}".encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def _client():
    from openai import OpenAI

    key = openrouter_key()
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Add it to .env before ingest/search."
        )
    return OpenAI(base_url=embed_base_url().rstrip("/") + "/", api_key=key)


def _zero() -> list[float]:
    return [0.0] * DIM


def _normalize(vec: list[float]) -> list[float]:
    arr = np.asarray(vec, dtype=float)
    n = float(np.linalg.norm(arr))
    if n == 0:
        return _zero()
    return (arr / n).tolist()


def _lookup(texts: list[str]) -> tuple[list[list[float] | None], list[int]]:
    conn = _cache()
    found: list[list[float] | None] = [None] * len(texts)
    missing: list[int] = []
    for i, text in enumerate(texts):
        row = conn.execute(
            "SELECT value FROM embeddings WHERE key = ?", (_cache_key(text),)
        ).fetchone()
        if row:
            found[i] = json.loads(row[0])
        else:
            missing.append(i)
    conn.close()
    return found, missing


def _api_embed(batch: list[str]) -> list[list[float]]:
    resp = _client().embeddings.create(model=_model_name(), input=batch)
    by_index = {item.index: item.embedding for item in resp.data}
    return [_normalize(by_index[i]) for i in range(len(batch))]


def embed_texts(texts: list[str], batch_size: int = MAX_BATCH) -> list[list[float]]:
    if not texts:
        return []

    prepared = [_clip_for_embed(t) for t in texts]
    results, missing = _lookup(prepared)
    pending = [prepared[i] for i in missing]
    filled: list[list[float]] = []
    size = max(1, min(batch_size, MAX_BATCH))
    conn = _cache()
    for start in range(0, len(pending), size):
        chunk = pending[start : start + size]
        vecs = _api_embed(chunk)
        filled.extend(vecs)
        for text, vec in zip(chunk, vecs):
            conn.execute(
                "INSERT OR REPLACE INTO embeddings(key, value) VALUES (?, ?)",
                (_cache_key(text), json.dumps(vec)),
            )
        conn.commit()
    conn.close()

    out: list[list[float]] = []
    iterator = iter(filled)
    for existing in results:
        if existing is None:
            out.append(next(iterator))
        else:
            out.append(existing)
    return out


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


def cosine(a: list[float], b: list[float]) -> float:
    va = np.asarray(a, dtype=float)
    vb = np.asarray(b, dtype=float)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)
