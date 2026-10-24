from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ledger.adapters.claude import list_conversations
from ledger.config import DEFAULT_CLAUDE_EXPORT, NORMALIZED_DIR


def _print(payload) -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ledger", description="Ledger decision-memory graph")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_titles = sub.add_parser("titles", help="List Claude export conversation titles")
    p_titles.add_argument("--input", type=Path, default=DEFAULT_CLAUDE_EXPORT)

    p_norm = sub.add_parser("normalize", help="Claude export → normalized JSONL")
    p_norm.add_argument("--input", type=Path, default=DEFAULT_CLAUDE_EXPORT)
    p_norm.add_argument("--output", type=Path, default=NORMALIZED_DIR / "claude.jsonl")
    p_norm.add_argument("--limit", type=int, default=None)
    p_norm.add_argument("--title-contains", type=str, default=None)

    p_redact = sub.add_parser("redact", help="Redact secrets in normalized JSONL")
    p_redact.add_argument("--input", type=Path, default=NORMALIZED_DIR / "claude.jsonl")
    p_redact.add_argument("--output", type=Path, default=NORMALIZED_DIR / "claude.redacted.jsonl")

    p_ingest = sub.add_parser("ingest", help="Normalize, redact, and load Conversation/Message nodes")
    p_ingest.add_argument("--input", type=Path, default=DEFAULT_CLAUDE_EXPORT)
    p_ingest.add_argument("--limit", type=int, default=None)
    p_ingest.add_argument("--title-contains", type=str, default=None)

    p_extract = sub.add_parser("extract", help="LLM-extract decisions/claims into the graph")
    p_extract.add_argument("--input", type=Path, default=NORMALIZED_DIR / "claude.redacted.jsonl")
    p_extract.add_argument("--limit", type=int, default=None)

    p_search = sub.add_parser("search", help="search_memory")
    p_search.add_argument("query")
    p_search.add_argument("-k", type=int, default=8)

    p_trace = sub.add_parser("trace", help="trace_decision")
    p_trace.add_argument("query")

    p_check = sub.add_parser("check", help="check_assumptions")
    p_check.add_argument("statement", nargs="?", default=None)

    p_rec = sub.add_parser("record", help="record_decision")
    p_rec.add_argument("--question", required=True)
    p_rec.add_argument("--choice", required=True)
    p_rec.add_argument("--rationale", default="")
    p_rec.add_argument("--options", default="")
    p_rec.add_argument("--assumptions", default="")

    p_forget = sub.add_parser("forget", help="Cascade-forget a conversation")
    p_forget.add_argument("target_id")
    p_forget.add_argument("--type", default="conversation")
    p_forget.add_argument("--apply", action="store_true", help="Actually delete (default is dry-run)")

    p_mcp = sub.add_parser("mcp", help="Run the MCP server over stdio")

    args = parser.parse_args(argv)

    if args.cmd == "titles":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        rows = list_conversations(args.input)
        for i, row in enumerate(rows):
            print(f"{i:03d} | {row['n_messages']:3d} msgs | {row['conv_id']} | {row['title']}")
        print(f"\n{len(rows)} conversations")
        return

    if args.cmd == "normalize":
        from ledger.pipeline import normalize_claude

        normalize_claude(args.input, args.output, limit=args.limit, title_contains=args.title_contains)
        return

    if args.cmd == "redact":
        from ledger.pipeline import redact_file

        redact_file(args.input, args.output)
        return

    if args.cmd == "ingest":
        from ledger.graph_store import GraphStore
        from ledger.pipeline import ingest_jsonl, normalize_claude, redact_file

        raw = normalize_claude(
            args.input,
            NORMALIZED_DIR / "claude.jsonl",
            limit=args.limit,
            title_contains=args.title_contains,
        )
        redacted = redact_file(raw, NORMALIZED_DIR / "claude.redacted.jsonl")
        store = GraphStore()
        ingest_jsonl(redacted, store)
        return

    if args.cmd == "extract":
        from ledger.pipeline import extract_into_graph

        extract_into_graph(args.input, limit=args.limit)
        return

    if args.cmd == "search":
        from ledger.retrieval import search_memory

        _print(search_memory(args.query, k=args.k))
        return

    if args.cmd == "trace":
        from ledger.retrieval import trace_decision

        _print(trace_decision(args.query))
        return

    if args.cmd == "check":
        from ledger.retrieval import check_assumptions

        _print(check_assumptions(args.statement))
        return

    if args.cmd == "record":
        from ledger.retrieval import record_decision

        _print(
            record_decision(
                args.question,
                [x.strip() for x in args.options.split(",") if x.strip()],
                args.choice,
                args.rationale,
                [x.strip() for x in args.assumptions.split(",") if x.strip()],
            )
        )
        return

    if args.cmd == "forget":
        from ledger.forget import forget

        _print(forget(args.target_id, args.type, dry_run=not args.apply))
        return

    if args.cmd == "mcp":
        from ledger.mcp_server import main as mcp_main

        mcp_main()


if __name__ == "__main__":
    main()
