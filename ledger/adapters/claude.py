"""Claude export → normalized conversation JSONL."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator

TOOL_JUNK = re.compile(
    r"(</?antml:[\w-]+[^>]*>|\[Tool (?:use|result)[^\]]*\]|attachment[:\s].*)",
    re.IGNORECASE,
)


UNSUPPORTED_BLOCK = "This block is not supported on your current device yet."


def _message_text(msg: dict[str, Any]) -> str:
    if isinstance(msg.get("text"), str) and msg["text"].strip():
        text = msg["text"].strip()
        text = text.replace(f"```\n{UNSUPPORTED_BLOCK}\n```", "").replace(UNSUPPORTED_BLOCK, "")
        return text.strip()

    content = msg.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                block_type = block.get("type")
                if block_type in (None, "text") and block.get("text"):
                    parts.append(str(block["text"]))
        return "\n".join(p.strip() for p in parts if p and p.strip())
    return ""


def _role(sender: str | None) -> str | None:
    if not sender:
        return None
    s = sender.lower()
    if s in {"human", "user"}:
        return "user"
    if s in {"assistant", "claude"}:
        return "assistant"
    return None


def normalize_conversation(raw: dict[str, Any]) -> dict[str, Any] | None:
    conv_id = raw.get("uuid") or raw.get("id")
    if not conv_id:
        return None

    messages_raw = raw.get("chat_messages") or raw.get("messages") or []
    messages: list[dict[str, Any]] = []
    idx = 0
    for msg in messages_raw:
        role = _role(msg.get("sender") or msg.get("role"))
        text = TOOL_JUNK.sub("", _message_text(msg)).strip()
        if not role or not text:
            continue
        messages.append(
            {
                "idx": idx,
                "role": role,
                "text": text,
                "ts": msg.get("created_at") or msg.get("updated_at") or "",
            }
        )
        idx += 1

    if not messages:
        return None

    return {
        "conv_id": str(conv_id),
        "source": "claude",
        "title": raw.get("name") or raw.get("title") or "(untitled)",
        "started_at": raw.get("created_at") or messages[0]["ts"],
        "messages": messages,
    }


def list_conversations(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Expected Claude conversations.json to be a JSON array")
    rows = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        msgs = raw.get("chat_messages") or raw.get("messages") or []
        rows.append(
            {
                "conv_id": raw.get("uuid") or raw.get("id"),
                "title": raw.get("name") or raw.get("title") or "(untitled)",
                "n_messages": len(msgs),
                "created_at": raw.get("created_at") or "",
            }
        )
    return rows


def iter_normalized(path: Path) -> Iterator[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Expected Claude conversations.json to be a JSON array")
    for raw in data:
        if isinstance(raw, dict):
            norm = normalize_conversation(raw)
            if norm:
                yield norm


def write_jsonl(
    input_path: Path,
    output_path: Path,
    *,
    limit: int | None = None,
    title_contains: str | None = None,
) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with output_path.open("w", encoding="utf-8") as out:
        for conv in iter_normalized(input_path):
            if title_contains and title_contains.lower() not in conv["title"].lower():
                continue
            out.write(json.dumps(conv, ensure_ascii=False) + "\n")
            n += 1
            if limit is not None and n >= limit:
                break
    return n
