Put personal exports under `private/`. That directory is gitignored.

```
data/private/
  conversations-000/conversations.json   # Claude takeout (example)
  normalized/claude.jsonl
  normalized/claude.redacted.jsonl
```

Synthetic fixtures for tests live in `tests/fixtures/`, not here.
