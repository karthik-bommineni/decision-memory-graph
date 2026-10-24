# Contributing

## Do not commit personal data

Keep exports, redacted JSONL, keys, and caches out of git. `.gitignore` already covers:

- `.env`
- `data/private/`
- `.cache/` and `*.sqlite`
- zip takeouts and stray `conversations.json`

Tests must use tiny synthetic fixtures under `tests/fixtures/`, never a real dump.

If you add a new adapter, add a **synthetic** fixture (a handful of messages) and a unittest. Do not paste your own chats into the PR.

## How the pipeline uses adapters

1. Adapter reads a vendor export → **normalized JSONL** (one conversation per line).
2. `ledger.redact` masks emails/keys.
3. `ingest` embeds messages and writes Conversation / Message nodes.
4. `extract` is source-agnostic. It only needs the JSONL shape below.

So a new product is **one adapter module**, plus CLI wiring. Do not fork extract or the graph schema per vendor.

## Normalized conversation contract

Every adapter must emit this object (and skip empty / tool-only threads):

```json
{
  "conv_id": "stable-id-from-the-export",
  "source": "chatgpt",
  "title": "short title",
  "started_at": "ISO-8601 or empty",
  "messages": [
    {
      "idx": 0,
      "role": "user",
      "text": "plain text only",
      "ts": "ISO-8601 or empty"
    }
  ]
}
```

Rules:

- `source` is a short slug: `claude`, `chatgpt`, `gemini`, `claude_code`, `antigravity`, `codex`, …
- `role` is only `user` or `assistant`. Drop system/tool/developer turns, or fold tool noise out of `text`.
- `idx` is 0-based in the **linear** transcript you keep (not the vendor's tree index).
- Strip markup the LLM should not see (tool XML, binary attachments, huge base64).
- `conv_id` must be stable across re-ingest so node ids stay the same.

Reference implementation: `ledger/adapters/claude.py` (`normalize_conversation`, `iter_normalized`, `write_jsonl`, `list_conversations`).

Suggested module API (match Claude so CLI/pipeline stay thin):

```python
def normalize_conversation(raw: dict) -> dict | None: ...
def iter_normalized(path: Path) -> Iterator[dict]: ...
def write_jsonl(input_path: Path, output_path: Path, *, limit: int | None = None, title_contains: str | None = None) -> int: ...
def list_conversations(path: Path) -> list[dict]: ...
```

Put files in `data/private/<source>/` locally. Write JSONL to `data/private/normalized/<source>.jsonl`.

Wire a CLI flag when the adapter is real, for example `python -m ledger.cli ingest --source chatgpt --input ...`. Until then, calling `write_jsonl` from a small script is fine.

## Adapter notes by source

None of these except **Claude web export** are implemented. `ledger/adapters/chatgpt.py` is a stub. Formats below are the usual public dumps; verify against a current export before coding.

### ChatGPT (OpenAI takeout)

Typical file: `conversations.json` (array of threads). Each thread is a **message tree** (`mapping` id → parent/children), not a list.

- Walk from the root along the **current** branch (the child OpenAI marked current), not every abandoned retry.
- `author.role` → `user` / `assistant`. Skip `system` and tool payloads unless the user text is empty and you need a short placeholder.
- `conv_id` = thread `id`. `started_at` from `create_time` (Unix seconds → ISO).
- Title from `title`.

### Gemini (Google)

Takeout / Gemini history is usually JSON or HTML per chat, with `user` / `model` turns.

- Map `model` → `assistant`.
- Prefer any UUID Google already assigned; otherwise hash `title + first timestamp`.
- Strip UI chrome and “exported from Gemini” footers.

### Claude Code

Session logs are often **JSONL** (one event per line) under a project `.claude/` or similar path — not the claude.ai `conversations.json` array.

- Linearize user/assistant text; drop tool-use / tool-result blocks or keep a one-line summary, not the full dump.
- `source`: `claude_code`. `conv_id`: session id from the filename or log header.
- Do not scrape another user's `.claude` directory in fixtures.

### Antigravity

Whatever export or on-disk session format that product ships (JSON, JSONL, or SQLite).

- Treat it like any other coding agent: user prompts + assistant replies, ignore internal traces if they dwarf the dialogue.
- `source`: `antigravity`. Document the file you reverse-engineered in the adapter docstring (no sample of real user prompts).

### Codex (OpenAI Codex / CLI sessions)

Session JSON or JSONL from the Codex app or CLI.

- Same linearize-the-active-thread rule as ChatGPT if the log is a tree.
- `source`: `codex`.
- Keep `conv_id` aligned with the session uuid so re-import updates in place.

## Tests

Mirror `tests/test_adapter.py`:

1. Tiny fixture JSON in `tests/fixtures/tiny_<source>.json`.
2. Assert `source`, `conv_id`, message count, roles, and that tool-only threads return `None`.
3. Run `python -m unittest discover -s tests`.

## Code style

- Keep adapters free of OpenRouter / FalkorDB imports. They only parse files.
- Prefer explicit skip of junk over stuffing tool JSON into `text`.
- Windows consoles are often cp1252; do not `print` raw emoji from adapters (the CLI already ascii-replaces titles).
- Stay on `mcp>=1.2.0,<2` until `ledger/mcp_server.py` is migrated to MCP 2 `MCPServer`.
