from __future__ import annotations

from typing import Any

from ledger.graph_store import GraphStore


def preview_forget(target_id: str, target_type: str, store: GraphStore | None = None) -> dict[str, Any]:
    store = store or GraphStore()
    target_type = target_type.lower()
    if target_type in {"conversation", "conv"}:
        conv_id = target_id
    elif target_type == "message":
        rec = store.query("MATCH (m:Message {id:$id}) RETURN m.conv_id", {"id": target_id}, read_only=True)
        if not rec.result_set:
            return {"error": "message not found"}
        conv_id = rec.result_set[0][0]
    else:
        rec = store.query(
            f"MATCH (n:{target_type.capitalize()} {{id:$id}})-[:EXTRACTED_FROM]->(m:Message) RETURN m.conv_id LIMIT 1",
            {"id": target_id},
            read_only=True,
        )
        if not rec.result_set:
            return {"error": f"{target_type} not found or has no provenance"}
        conv_id = rec.result_set[0][0]

    derived = store.query(
        """
        MATCH (n)-[:EXTRACTED_FROM]->(m:Message {conv_id:$cid})
        RETURN DISTINCT labels(n)[0], n.id
        """,
        {"cid": conv_id},
        read_only=True,
    )
    orphans = []
    kept = []
    for label, nid in derived.result_set:
        other = store.query(
            """
            MATCH (n {id:$id})-[:EXTRACTED_FROM]->(m:Message)
            WHERE m.conv_id <> $cid
            RETURN count(m)
            """,
            {"id": nid, "cid": conv_id},
            read_only=True,
        )
        remaining = other.result_set[0][0] if other.result_set else 0
        if remaining == 0:
            orphans.append({"label": label, "id": nid})
        else:
            kept.append({"label": label, "id": nid, "remaining_sources": remaining})

    needs_review = store.query(
        """
        MATCH (d:Decision)-[:DEPENDS_ON]->(c:Claim)
        WHERE c.id IN $ids
        RETURN d.id, d.question
        """,
        {"ids": [row["id"] for row in orphans if row["label"] == "Claim"]},
        read_only=True,
    )
    return {
        "conversation_id": conv_id,
        "would_delete": orphans,
        "would_keep": kept,
        "decisions_needs_review": [{"id": r[0], "question": r[1]} for r in needs_review.result_set],
        "dry_run": True,
    }


def forget(target_id: str, target_type: str, *, dry_run: bool = True, store: GraphStore | None = None) -> dict[str, Any]:
    store = store or GraphStore()
    preview = preview_forget(target_id, target_type, store)
    if preview.get("error") or dry_run:
        return preview
    conv_id = preview["conversation_id"]
    for node in preview["would_delete"]:
        store.query(f"MATCH (n:{node['label']} {{id:$id}}) DETACH DELETE n", {"id": node["id"]})
    for dec in preview["decisions_needs_review"]:
        store.query(
            "MATCH (d:Decision {id:$id}) SET d.status = 'stale', d.stale_reason = 'needs_review after forget'",
            {"id": dec["id"]},
        )
    store.query("MATCH (c:Conversation {id:$id})-[:HAS_MESSAGE]->(m:Message) DETACH DELETE m", {"id": conv_id})
    store.query("MATCH (c:Conversation {id:$id}) DETACH DELETE c", {"id": conv_id})
    preview["dry_run"] = False
    preview["deleted"] = True
    return preview
