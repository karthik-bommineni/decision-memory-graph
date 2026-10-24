from __future__ import annotations

import json

from ledger.forget import forget as _forget
from ledger.retrieval import check_assumptions as _check
from ledger.retrieval import record_decision as _record
from ledger.retrieval import search_memory as _search
from ledger.retrieval import trace_decision as _trace

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover
    from mcp.server.fastmcp.server import FastMCP

mcp = FastMCP("ledger")


def _dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


@mcp.tool()
def search_memory(query: str, k: int = 8, kinds: str = "claim,decision,workflow") -> str:
    """Hybrid recall across claims, decisions, and workflows."""
    kind_list = [x.strip() for x in kinds.split(",") if x.strip()]
    return _dumps(_search(query, k=k, kinds=kind_list))


@mcp.tool()
def trace_decision(query_or_id: str) -> str:
    """Return the full why-path for a decision: options, rationale, assumptions, sources."""
    return _dumps(_trace(query_or_id))


@mcp.tool()
def check_assumptions(statement: str = "") -> str:
    """List stale decisions, or dry-run impact of a new statement."""
    return _dumps(_check(statement or None))


@mcp.tool()
def record_decision(
    question: str,
    choice: str,
    rationale: str,
    options: str = "",
    assumptions: str = "",
) -> str:
    """Write a live decision into the graph. options and assumptions are comma-separated."""
    opt = [x.strip() for x in options.split(",") if x.strip()]
    assum = [x.strip() for x in assumptions.split(",") if x.strip()]
    return _dumps(_record(question, opt, choice, rationale, assum))


@mcp.tool()
def forget(target_id: str, target_type: str = "conversation", dry_run: bool = True) -> str:
    """Provenance cascade delete. Always preview with dry_run=true first."""
    return _dumps(_forget(target_id, target_type, dry_run=dry_run))


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
