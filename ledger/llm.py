from __future__ import annotations

import hashlib
import json
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

from ledger.config import CACHE_DIR, embed_base_url, extract_model, openrouter_key

DB_PATH = CACHE_DIR / "llm_cache.sqlite"
EMPTY = {"entities": [], "claims": [], "decisions": [], "workflows": []}


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    return conn


def _key(*parts: str) -> str:
    return hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def _client():
    from openai import OpenAI

    key = openrouter_key()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set. Add it to .env before extraction.")
    return OpenAI(base_url=embed_base_url().rstrip("/") + "/", api_key=key)


def _llm_call(system: str, user: str, model: str, max_tokens: int, *, json_mode: bool) -> str:
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        resp = _client().chat.completions.create(**kwargs)
    except Exception:
        if not json_mode:
            raise
        kwargs.pop("response_format", None)
        resp = _client().chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "").strip()


def cached_complete(system: str, user: str, *, model: str | None = None, max_tokens: int = 8192) -> str:
    use_model = model or extract_model()
    cache_key = _key(use_model, system, user)
    conn = _db()
    row = conn.execute("SELECT value FROM cache WHERE key = ?", (cache_key,)).fetchone()
    if row:
        conn.close()
        return row[0]
    text = _llm_call(system, user, use_model, max_tokens, json_mode=False)
    conn = _db()
    conn.execute("INSERT OR REPLACE INTO cache(key, value) VALUES (?, ?)", (cache_key, text))
    conn.commit()
    conn.close()
    return text


def parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in model output: {text[:240]}")
    return json.loads(text[start : end + 1])


def complete_json(system: str, user: str, *, model: str | None = None) -> dict[str, Any]:
    use_model = model or extract_model()
    cache_key = _key("json", use_model, system, user)
    conn = _db()
    row = conn.execute("SELECT value FROM cache WHERE key = ?", (cache_key,)).fetchone()
    if row:
        try:
            parsed = json.loads(row[0])
            if isinstance(parsed, dict):
                conn.close()
                return parsed
        except Exception:
            conn.execute("DELETE FROM cache WHERE key = ?", (cache_key,))
            conn.commit()
    conn.close()

    raw = cached_complete(system, user, model=use_model, max_tokens=8192)
    try:
        parsed = parse_json_object(raw)
    except Exception:
        try:
            raw = _llm_call(
                "Return only valid compact JSON. No markdown.",
                user[:12000],
                use_model,
                4096,
                json_mode=True,
            )
            parsed = parse_json_object(raw)
        except Exception:
            print("  skipped window: model returned invalid JSON")
            return dict(EMPTY)

    conn = _db()
    conn.execute(
        "INSERT OR REPLACE INTO cache(key, value) VALUES (?, ?)",
        (cache_key, json.dumps(parsed)),
    )
    conn.commit()
    conn.close()
    return parsed if isinstance(parsed, dict) else dict(EMPTY)


def cache_path() -> Path:
    return DB_PATH
