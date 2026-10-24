from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?){2}\d{4}\b")
AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
OPENAI = re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")
ANTHROPIC = re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{20,}\b")
GOOGLE = re.compile(r"\bAIza[0-9A-Za-z\-_]{20,}\b")
GENERIC_TOKEN = re.compile(r"\b(?:ghp|gho|github_pat)_[A-Za-z0-9_]{20,}\b")
BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9\-._~+/]+=*")
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")


def redact_text(text: str) -> str:
    text = ANTHROPIC.sub("[REDACTED_ANTHROPIC_KEY]", text)
    text = OPENAI.sub("[REDACTED_API_KEY]", text)
    text = GOOGLE.sub("[REDACTED_GOOGLE_KEY]", text)
    text = AWS_KEY.sub("[REDACTED_AWS_KEY]", text)
    text = GENERIC_TOKEN.sub("[REDACTED_TOKEN]", text)
    text = JWT.sub("[REDACTED_JWT]", text)
    text = BEARER.sub(r"\1[REDACTED_BEARER]", text)
    text = EMAIL.sub("[REDACTED_EMAIL]", text)
    text = PHONE.sub("[REDACTED_PHONE]", text)
    return text


def redact_conversation(conv: dict[str, Any]) -> dict[str, Any]:
    out = dict(conv)
    out["title"] = redact_text(str(conv.get("title") or ""))
    msgs = []
    for msg in conv.get("messages") or []:
        item = dict(msg)
        item["text"] = redact_text(str(msg.get("text") or ""))
        msgs.append(item)
    out["messages"] = msgs
    return out


def redact_jsonl(input_path: Path, output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with input_path.open(encoding="utf-8") as src, output_path.open("w", encoding="utf-8") as dst:
        for line in src:
            line = line.strip()
            if not line:
                continue
            conv = json.loads(line)
            dst.write(json.dumps(redact_conversation(conv), ensure_ascii=False) + "\n")
            n += 1
    return n
