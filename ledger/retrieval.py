from __future__ import annotations

import json
from typing import Any

from ledger.embeddings import cosine, embed_text
from ledger.graph_store import GraphStore
from ledger.ids import nid
from ledger.reconcile import propagate_staleness


def _node_dump(store: GraphStore, label: str, limit: int = 200) -> list[dict[str, Any]]:
    if label == "Claim":
        q = "MATCH (n:Claim) RETURN n.id, n.text, n.kind, n.status, n.predicate_key, n.embedding_json LIMIT $limit"
    elif label == "Decision":
        q = "MATCH (n:Decision) RETURN n.id, n.question, n.choice, n.status, n.rationale, n.embedding_json, n.options, n.stale_reason LIMIT $limit"
    elif label == "Workflow":
        q = "MATCH (n:Workflow) WHERE n.times_seen >= 2 RETURN n.id, n.name, n.steps, n.times_seen, n.embedding_json LIMIT $limit"
    else:
        q = "MATCH (n:Message) RETURN n.id, n.text, n.role, n.conv_id, n.ts, n.embedding_json LIMIT $limit"
    result = store.query(q, {"limit": limit}, read_only=True)
    rows = []
    for rec in result.result_set:
        rows.append({"raw": rec, "embedding": json.loads(rec[-1] or "[]") if label != "Decision" else json.loads(rec[5] or "[]")})
        if label == "Decision":
            rows[-1]["embedding"] = json.loads(rec[5] or "[]")
    return rows


def _sources_for(store: GraphStore, label: str, node_id: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    result = store.query(
        f"""
        MATCH (n:{label} {{id: $id}})-[:EXTRACTED_FROM]->(m:Message)<-[:HAS_MESSAGE]-(c:Conversation)
        RETURN c.title, c.started_at, m.text, m.id, n.id
        """,
        {"id": node_id},
        read_only=True,
    )
    sources = []
    path = []
    for rec in result.result_set:
        snippet = (rec[2] or "")[:240]
        sources.append({"conversation": rec[0], "date": rec[1] or "", "snippet": snippet})
        path.append({"from": rec[4], "rel": "EXTRACTED_FROM", "to": rec[3]})
    return path, sources


def search_memory(query: str, k: int = 8, kinds: list[str] | None = None, store: GraphStore | None = None) -> dict[str, Any]:
    store = store or GraphStore()
    qvec = embed_text(query)
    kinds = kinds or ["claim", "decision", "workflow"]
    items = []

    def add_label(label: str, kind: str) -> None:
        scored = store.vector_query(label, qvec, k=k)
        if not scored:
            for row in _node_dump(store, label):
                if row["embedding"]:
                    scored.append((row["raw"][0], cosine(qvec, row["embedding"])))
            scored.sort(key=lambda x: x[1], reverse=True)
            scored = scored[:k]
        for node_id, score in scored:
            path, sources = _sources_for(store, label, node_id)
            if label == "Claim":
                rec = store.query(
                    "MATCH (c:Claim {id:$id}) RETURN c.text, c.status, c.kind",
                    {"id": node_id},
                    read_only=True,
                )
                if not rec.result_set:
                    continue
                text, status, ck = rec.result_set[0]
                items.append(
                    {
                        "kind": kind,
                        "id": node_id,
                        "text": text,
                        "status": status,
                        "claim_kind": ck,
                        "score": float(score),
                        "evidence_path": path,
                        "sources": sources,
                    }
                )
            elif label == "Decision":
                rec = store.query(
                    "MATCH (d:Decision {id:$id}) RETURN d.question, d.choice, d.status, d.rationale",
                    {"id": node_id},
                    read_only=True,
                )
                if not rec.result_set:
                    continue
                question, choice, status, rationale = rec.result_set[0]
                items.append(
                    {
                        "kind": kind,
                        "id": node_id,
                        "text": f"{question} -> {choice}",
                        "status": status,
                        "rationale": rationale,
                        "score": float(score),
                        "evidence_path": path,
                        "sources": sources,
                    }
                )
            else:
                rec = store.query(
                    "MATCH (w:Workflow {id:$id}) RETURN w.name, w.steps, w.times_seen",
                    {"id": node_id},
                    read_only=True,
                )
                if not rec.result_set:
                    continue
                name, steps, times_seen = rec.result_set[0]
                items.append(
                    {
                        "kind": kind,
                        "id": node_id,
                        "text": name,
                        "steps": steps,
                        "times_seen": times_seen,
                        "score": float(score),
                        "evidence_path": path,
                        "sources": sources,
                    }
                )

    mapping = {"claim": "Claim", "decision": "Decision", "workflow": "Workflow"}
    for kind in kinds:
        label = mapping.get(kind.lower())
        if label:
            add_label(label, kind.lower())
    items.sort(key=lambda x: x.get("score") or 0, reverse=True)
    return {"query": query, "items": items[:k]}


def trace_decision(query_or_id: str, store: GraphStore | None = None) -> dict[str, Any]:
    store = store or GraphStore()
    rec = store.query(
        "MATCH (d:Decision {id:$id}) RETURN d.id, d.question, d.choice, d.options, d.rationale, d.status, d.stale_reason",
        {"id": query_or_id},
        read_only=True,
    )
    if not rec.result_set:
        hits = search_memory(query_or_id, k=1, kinds=["decision"], store=store)
        if not hits["items"]:
            return {"error": "no decision found", "query": query_or_id}
        query_or_id = hits["items"][0]["id"]
        rec = store.query(
            "MATCH (d:Decision {id:$id}) RETURN d.id, d.question, d.choice, d.options, d.rationale, d.status, d.stale_reason",
            {"id": query_or_id},
            read_only=True,
        )
    d = rec.result_set[0]
    deps = store.query(
        """
        MATCH (d:Decision {id:$id})-[:DEPENDS_ON]->(c:Claim)
        OPTIONAL MATCH (n:Claim)-[:SUPERSEDES]->(c)
        RETURN c.id, c.text, c.status, n.id, n.text
        """,
        {"id": d[0]},
        read_only=True,
    )
    assumptions = []
    for row in deps.result_set:
        assumptions.append(
            {
                "id": row[0],
                "text": row[1],
                "status": row[2],
                "superseding_id": row[3],
                "superseding_text": row[4],
            }
        )
    path, sources = _sources_for(store, "Decision", d[0])
    return {
        "id": d[0],
        "question": d[1],
        "choice": d[2],
        "options": d[3] or [],
        "rationale": d[4],
        "verdict": d[5],
        "stale_reason": d[6],
        "assumptions": assumptions,
        "evidence_path": path,
        "sources": sources,
    }


def check_assumptions(statement: str | None = None, store: GraphStore | None = None) -> dict[str, Any]:
    store = store or GraphStore()
    stale = store.query(
        """
        MATCH (d:Decision {status:'stale'})
        RETURN d.id, d.question, d.choice, d.stale_reason
        """,
        read_only=True,
    )
    suggested = store.query(
        "MATCH (c:Claim {status:'suggested'}) RETURN c.id, c.text",
        read_only=True,
    )
    payload: dict[str, Any] = {
        "stale_decisions": [
            {"id": r[0], "question": r[1], "choice": r[2], "reason": r[3]} for r in stale.result_set
        ],
        "suggested_supersessions": [{"id": r[0], "text": r[1]} for r in suggested.result_set],
    }
    if statement:
        qvec = embed_text(statement)
        impacted = []
        for claim in store.active_claims():
            if not claim.get("embedding"):
                continue
            score = cosine(qvec, claim["embedding"])
            if score < 0.75:
                continue
            deps = store.query(
                """
                MATCH (d:Decision {status:'active'})-[:DEPENDS_ON]->(c:Claim {id:$id})
                RETURN d.id, d.question, d.choice
                """,
                {"id": claim["id"]},
                read_only=True,
            )
            if deps.result_set:
                impacted.append(
                    {
                        "claim_id": claim["id"],
                        "claim": claim["text"],
                        "similarity": score,
                        "decisions": [
                            {"id": r[0], "question": r[1], "choice": r[2]} for r in deps.result_set
                        ],
                    }
                )
        payload["statement"] = statement
        payload["would_go_stale"] = impacted
    return payload


def record_decision(
    question: str,
    options: list[str],
    choice: str,
    rationale: str,
    assumptions: list[str],
    store: GraphStore | None = None,
) -> dict[str, Any]:
    store = store or GraphStore()
    store.ensure_schema()
    dec_id = nid("decision", "live", question, choice)
    embedding = embed_text(f"{question} {choice}")
    store.upsert_decision(
        {
            "id": dec_id,
            "question": question,
            "choice": choice,
            "options": options,
            "rationale": rationale,
            "decided_at": "",
            "status": "active",
            "embedding": embedding,
        }
    )
    linked = []
    for text in assumptions:
        from ledger.pipeline import _match_assumption

        cid = _match_assumption(store, text, None)
        store.relate_depends(dec_id, cid)
        linked.append(cid)
    propagate_staleness(store)
    return {"decision_id": dec_id, "assumption_ids": linked}
