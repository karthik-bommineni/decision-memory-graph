from __future__ import annotations

import json
from typing import Any

from ledger.llm import complete_json
from ledger.models import ExtractionResult

SYSTEM = """You extract a personal decision-memory graph from one AI chat.
Return ONLY JSON with keys: entities, claims, decisions, workflows.

Rules:
- Extract only what the USER stated, preferred, or decided. Do not treat assistant advice as a user decision unless the user clearly accepted it.
- Skip chit-chat, tutorials with no personal choice, and generic Q&A.
- entities[].type must be one of: person, project, tool, org, topic.
- Every claim MUST include: text, kind, subject, predicate_key, evidence_msg_idx.
- claims[].kind must be one of: fact, preference, constraint, assumption.
- claims[].predicate_key is a short snake_case key like laptop_budget or db_choice.
- claims[].evidence_msg_idx and decisions[].evidence_msg_idx must be message indexes from the input.
- Every decision MUST include: question, choice, rationale, options, assumptions, evidence_msg_idx.
- decisions capture a real choice among options, plus rationale and assumptions the choice depends on.
- assumptions are conditions the decision relies on, not extra commentary.
- workflows are recurring procedural patterns the user asked for more than once. If none, use [].
"""

_CLAIM_KINDS = {"fact", "preference", "constraint", "assumption"}
_ENTITY_TYPES = {"person", "project", "tool", "org", "topic"}


def _window_messages(messages: list[dict[str, Any]], size: int = 8) -> list[list[dict[str, Any]]]:
    if len(messages) <= size:
        return [messages]
    windows = []
    i = 0
    while i < len(messages):
        windows.append(messages[i : i + size])
        i += size
    return windows


def _first_str(item: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if val is not None and not isinstance(val, (dict, list)):
            text = str(val).strip()
            if text:
                return text
    return default


def _idx(item: dict[str, Any]) -> int:
    for key in ("evidence_msg_idx", "msg_idx", "message_idx", "idx"):
        val = item.get(key)
        if isinstance(val, int):
            return val
        if isinstance(val, str) and val.isdigit():
            return int(val)
    return 0


def _sanitize(data: dict[str, Any]) -> dict[str, Any]:
    entities = []
    for raw in data.get("entities") or []:
        if not isinstance(raw, dict):
            continue
        name = _first_str(raw, "name", "text", "title")
        etype = _first_str(raw, "type", default="topic").lower()
        if etype not in _ENTITY_TYPES:
            etype = "topic"
        if name:
            aliases = raw.get("aliases") or []
            if not isinstance(aliases, list):
                aliases = []
            entities.append({"name": name, "type": etype, "aliases": [str(a) for a in aliases]})

    claims = []
    for raw in data.get("claims") or []:
        if not isinstance(raw, dict):
            continue
        text = _first_str(raw, "text", "claim", "statement", "content", "value")
        if not text:
            continue
        kind = _first_str(raw, "kind", default="fact").lower()
        if kind not in _CLAIM_KINDS:
            kind = "fact"
        claims.append(
            {
                "text": text,
                "kind": kind,
                "subject": _first_str(raw, "subject", "entity", "about", "topic", default="unknown"),
                "predicate_key": _first_str(raw, "predicate_key", "predicate", "key", default="claim"),
                "evidence_msg_idx": _idx(raw),
                "confidence": float(raw["confidence"]) if isinstance(raw.get("confidence"), (int, float)) else 0.7,
            }
        )

    decisions = []
    for raw in data.get("decisions") or []:
        if not isinstance(raw, dict):
            continue
        choice = _first_str(raw, "choice", "decision", "selected")
        if not choice:
            continue
        options = raw.get("options") or []
        if not isinstance(options, list):
            options = []
        assumptions = raw.get("assumptions") or []
        if not isinstance(assumptions, list):
            assumptions = []
        decisions.append(
            {
                "question": _first_str(raw, "question", "prompt", "problem", default="What did I choose?"),
                "choice": choice,
                "options": [str(o) for o in options],
                "rationale": _first_str(raw, "rationale", "reason", "why"),
                "assumptions": [str(a) for a in assumptions],
                "evidence_msg_idx": _idx(raw),
            }
        )

    workflows = []
    for raw in data.get("workflows") or []:
        if not isinstance(raw, dict):
            continue
        name = _first_str(raw, "name", "title", "text")
        if not name:
            continue
        steps = raw.get("steps") or []
        if not isinstance(steps, list):
            steps = []
        workflows.append({"name": name, "steps": [str(s) for s in steps], "evidence_msg_idx": _idx(raw)})

    return {
        "entities": entities,
        "claims": claims,
        "decisions": decisions,
        "workflows": workflows,
    }


def extract_conversation(conv: dict[str, Any]) -> ExtractionResult:
    merged = ExtractionResult()
    windows = _window_messages(conv.get("messages") or [])
    for i, window in enumerate(windows, start=1):
        print(f"  window {i}/{len(windows)}", flush=True)
        payload = {
            "title": conv.get("title"),
            "started_at": conv.get("started_at"),
            "messages": [
                {"idx": m["idx"], "role": m["role"], "text": m["text"][:1500], "ts": m.get("ts")}
                for m in window
            ],
        }
        user = (
            "Extract entities/claims/decisions/workflows from this conversation JSON.\n"
            "Each claim needs text, kind, subject, predicate_key, evidence_msg_idx.\n"
            "Each decision needs question, choice, rationale, options, assumptions, evidence_msg_idx.\n"
            + json.dumps(payload, ensure_ascii=False)
        )
        try:
            data = complete_json(SYSTEM, user)
            part = ExtractionResult.model_validate(_sanitize(data if isinstance(data, dict) else {}))
        except Exception as exc:
            print(f"  skipped window: {exc}", flush=True)
            continue
        merged.entities.extend(part.entities)
        merged.claims.extend(part.claims)
        merged.decisions.extend(part.decisions)
        merged.workflows.extend(part.workflows)
    return merged
