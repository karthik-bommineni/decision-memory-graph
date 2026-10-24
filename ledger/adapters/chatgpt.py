"""ChatGPT export adapter (stub until conversations.json from OpenAI is available)."""

from __future__ import annotations

from pathlib import Path


def write_jsonl(input_path: Path, output_path: Path, **_: object) -> int:
    raise NotImplementedError(
        f"ChatGPT adapter is not wired yet. See CONTRIBUTING.md. Expected OpenAI conversations.json at {input_path}."
    )
