from __future__ import annotations

import hashlib


def nid(*parts: str) -> str:
    raw = "|".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:20]


def message_id(source: str, conv_id: str, idx: int) -> str:
    return nid("msg", source, conv_id, str(idx))
