from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

PRIVATE_DIR = ROOT / "data" / "private"
DEFAULT_CLAUDE_EXPORT = PRIVATE_DIR / "conversations-000" / "conversations.json"
NORMALIZED_DIR = PRIVATE_DIR / "normalized"
CACHE_DIR = ROOT / ".cache"
CACHE_DIR.mkdir(exist_ok=True)


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    return value if value not in (None, "") else default


def user_id() -> str:
    return env("LEDGER_USER", "default") or "default"


def graph_name() -> str:
    return f"user_{user_id()}"


def falkor_host() -> str:
    return env("FALKORDB_HOST", "localhost") or "localhost"


def falkor_port() -> int:
    return int(env("FALKORDB_PORT", "6379") or "6379")


def openrouter_key() -> str | None:
    return env("OPENROUTER_API_KEY")


def embed_base_url() -> str:
    return env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1") or "https://openrouter.ai/api/v1"


def embed_model() -> str:
    return env("LEDGER_EMBED_MODEL", "openai/text-embedding-3-small") or "openai/text-embedding-3-small"


def extract_model() -> str:
    return env("LEDGER_EXTRACT_MODEL", "anthropic/claude-haiku-4.5") or "anthropic/claude-haiku-4.5"


def adjudicate_model() -> str:
    return env("LEDGER_ADJUDICATE_MODEL", "anthropic/claude-sonnet-4.5") or "anthropic/claude-sonnet-4.5"
