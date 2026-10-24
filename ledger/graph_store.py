from __future__ import annotations

import json
from typing import Any

from ledger.config import falkor_host, falkor_port, graph_name
from ledger.embeddings import DIM
from ledger.ids import message_id


def vec_literal(values: list[float] | None) -> str:
    if not values:
        values = [0.0] * DIM
    cleaned = [float(x) for x in values[:DIM]]
    if len(cleaned) < DIM:
        cleaned.extend([0.0] * (DIM - len(cleaned)))
    return "[" + ",".join(f"{x:.6f}" for x in cleaned) + "]"


class GraphStore:
    def __init__(self, name: str | None = None) -> None:
        from falkordb import FalkorDB

        self.name = name or graph_name()
        self.db = FalkorDB(host=falkor_host(), port=falkor_port())
        self.g = self.db.select_graph(self.name)

    def query(self, cypher: str, params: dict[str, Any] | None = None, *, read_only: bool = False):
        if read_only:
            return self.g.ro_query(cypher, params or {})
        return self.g.query(cypher, params or {})

    def ping(self) -> None:
        self.query("RETURN 1")

    def ensure_schema(self) -> None:
        index_stmts = [
            "CREATE INDEX FOR (m:Message) ON (m.id)",
            "CREATE INDEX FOR (c:Conversation) ON (c.id)",
            "CREATE INDEX FOR (c:Claim) ON (c.id)",
            "CREATE INDEX FOR (d:Decision) ON (d.id)",
            "CREATE INDEX FOR (e:Entity) ON (e.id)",
            "CREATE INDEX FOR (c:Claim) ON (c.predicate_key)",
            f"CREATE VECTOR INDEX FOR (c:Claim) ON (c.embedding) OPTIONS {{dimension:{DIM}, similarityFunction:'cosine'}}",
            f"CREATE VECTOR INDEX FOR (d:Decision) ON (d.embedding) OPTIONS {{dimension:{DIM}, similarityFunction:'cosine'}}",
            f"CREATE VECTOR INDEX FOR (m:Message) ON (m.embedding) OPTIONS {{dimension:{DIM}, similarityFunction:'cosine'}}",
            "CREATE FULLTEXT INDEX FOR (c:Claim) ON (c.text)",
        ]
        for stmt in index_stmts:
            try:
                self.query(stmt)
            except Exception:
                # Already exists, or this FalkorDB build uses slightly different syntax.
                pass

    def upsert_conversation(self, conv: dict[str, Any], embeddings: list[list[float]]) -> None:
        self.query(
            """
            MERGE (c:Conversation {id: $id})
            SET c.source = $source, c.title = $title, c.started_at = $started_at
            """,
            {
                "id": conv["conv_id"],
                "source": conv.get("source") or "unknown",
                "title": conv.get("title") or "(untitled)",
                "started_at": conv.get("started_at") or "",
            },
        )
        messages = conv.get("messages") or []
        for msg, vec in zip(messages, embeddings):
            mid = message_id(conv.get("source") or "unknown", conv["conv_id"], int(msg["idx"]))
            vec_s = vec_literal(vec)
            self.query(
                f"""
                MATCH (c:Conversation {{id: $cid}})
                MERGE (m:Message {{id: $id}})
                SET m.conv_id = $cid,
                    m.idx = $idx,
                    m.role = $role,
                    m.text = $text,
                    m.ts = $ts,
                    m.embedding_json = $embedding_json,
                    m.embedding = vecf32({vec_s})
                MERGE (c)-[:HAS_MESSAGE {{idx: $idx}}]->(m)
                """,
                {
                    "cid": conv["conv_id"],
                    "id": mid,
                    "idx": int(msg["idx"]),
                    "role": msg.get("role") or "user",
                    "text": msg.get("text") or "",
                    "ts": msg.get("ts") or "",
                    "embedding_json": json.dumps(vec),
                },
            )

    def upsert_entity(self, entity_id: str, name: str, etype: str, aliases: list[str], embedding: list[float]) -> None:
        vec_s = vec_literal(embedding)
        self.query(
            f"""
            MERGE (e:Entity {{id: $id}})
            SET e.name = $name,
                e.type = $type,
                e.aliases = $aliases,
                e.embedding_json = $embedding_json,
                e.embedding = vecf32({vec_s})
            """,
            {
                "id": entity_id,
                "name": name,
                "type": etype,
                "aliases": aliases,
                "embedding_json": json.dumps(embedding),
            },
        )

    def upsert_claim(self, claim: dict[str, Any]) -> None:
        vec_s = vec_literal(claim.get("embedding"))
        self.query(
            f"""
            MERGE (c:Claim {{id: $id}})
            SET c.text = $text,
                c.kind = $kind,
                c.predicate_key = $predicate_key,
                c.status = $status,
                c.valid_from = $valid_from,
                c.valid_to = $valid_to,
                c.confidence = $confidence,
                c.embedding_json = $embedding_json,
                c.embedding = vecf32({vec_s})
            """,
            {
                "id": claim["id"],
                "text": claim["text"],
                "kind": claim.get("kind") or "fact",
                "predicate_key": claim.get("predicate_key") or "",
                "status": claim.get("status") or "active",
                "valid_from": claim.get("valid_from") or "",
                "valid_to": claim.get("valid_to") or "",
                "confidence": float(claim.get("confidence") or 0.7),
                "embedding_json": json.dumps(claim.get("embedding") or []),
            },
        )

    def upsert_decision(self, decision: dict[str, Any]) -> None:
        vec_s = vec_literal(decision.get("embedding"))
        self.query(
            f"""
            MERGE (d:Decision {{id: $id}})
            SET d.question = $question,
                d.choice = $choice,
                d.options = $options,
                d.rationale = $rationale,
                d.decided_at = $decided_at,
                d.status = $status,
                d.stale_reason = $stale_reason,
                d.embedding_json = $embedding_json,
                d.embedding = vecf32({vec_s})
            """,
            {
                "id": decision["id"],
                "question": decision.get("question") or "",
                "choice": decision.get("choice") or "",
                "options": decision.get("options") or [],
                "rationale": decision.get("rationale") or "",
                "decided_at": decision.get("decided_at") or "",
                "status": decision.get("status") or "active",
                "stale_reason": decision.get("stale_reason") or "",
                "embedding_json": json.dumps(decision.get("embedding") or []),
            },
        )

    def upsert_workflow(self, wf: dict[str, Any]) -> None:
        vec_s = vec_literal(wf.get("embedding"))
        self.query(
            f"""
            MERGE (w:Workflow {{id: $id}})
            SET w.name = $name,
                w.steps = $steps,
                w.times_seen = $times_seen,
                w.embedding_json = $embedding_json,
                w.embedding = vecf32({vec_s})
            """,
            {
                "id": wf["id"],
                "name": wf.get("name") or "",
                "steps": wf.get("steps") or [],
                "times_seen": int(wf.get("times_seen") or 1),
                "embedding_json": json.dumps(wf.get("embedding") or []),
            },
        )

    def relate_extracted(self, node_label: str, node_id: str, message_id_value: str) -> None:
        self.query(
            f"""
            MATCH (n:{node_label} {{id: $nid}})
            MATCH (m:Message {{id: $mid}})
            MERGE (n)-[:EXTRACTED_FROM]->(m)
            """,
            {"nid": node_id, "mid": message_id_value},
        )

    def relate_about(self, node_label: str, node_id: str, entity_id: str) -> None:
        self.query(
            f"""
            MATCH (n:{node_label} {{id: $nid}})
            MATCH (e:Entity {{id: $eid}})
            MERGE (n)-[:ABOUT]->(e)
            """,
            {"nid": node_id, "eid": entity_id},
        )

    def relate_depends(self, decision_id: str, claim_id: str) -> None:
        self.query(
            """
            MATCH (d:Decision {id: $did})
            MATCH (c:Claim {id: $cid})
            MERGE (d)-[:DEPENDS_ON]->(c)
            """,
            {"did": decision_id, "cid": claim_id},
        )

    def relate_supersedes(self, label: str, new_id: str, old_id: str) -> None:
        self.query(
            f"""
            MATCH (n:{label} {{id: $new_id}})
            MATCH (o:{label} {{id: $old_id}})
            MERGE (n)-[:SUPERSEDES]->(o)
            SET o.status = 'superseded'
            """,
            {"new_id": new_id, "old_id": old_id},
        )

    def set_claim_status(self, claim_id: str, status: str, valid_to: str = "") -> None:
        self.query(
            "MATCH (c:Claim {id: $id}) SET c.status = $status, c.valid_to = $valid_to",
            {"id": claim_id, "status": status, "valid_to": valid_to},
        )

    def mark_stale(self, decision_id: str, reason: str) -> None:
        self.query(
            "MATCH (d:Decision {id: $id}) SET d.status = 'stale', d.stale_reason = $reason",
            {"id": decision_id, "reason": reason},
        )

    def all_entities(self) -> list[dict[str, Any]]:
        result = self.query(
            "MATCH (e:Entity) RETURN e.id, e.name, e.type, e.aliases, e.embedding_json",
            read_only=True,
        )
        rows = []
        for rec in result.result_set:
            rows.append(
                {
                    "id": rec[0],
                    "name": rec[1],
                    "type": rec[2],
                    "aliases": rec[3] or [],
                    "embedding": json.loads(rec[4] or "[]"),
                }
            )
        return rows

    def active_claims(self) -> list[dict[str, Any]]:
        result = self.query(
            """
            MATCH (c:Claim)
            WHERE c.status IN ['active', 'suggested']
            OPTIONAL MATCH (c)-[:ABOUT]->(e:Entity)
            RETURN c.id, c.text, c.kind, c.predicate_key, c.status, c.confidence,
                   c.valid_from, c.embedding_json, e.id, e.name
            """,
            read_only=True,
        )
        rows = []
        for rec in result.result_set:
            rows.append(
                {
                    "id": rec[0],
                    "text": rec[1],
                    "kind": rec[2],
                    "predicate_key": rec[3],
                    "status": rec[4],
                    "confidence": rec[5],
                    "valid_from": rec[6],
                    "embedding": json.loads(rec[7] or "[]"),
                    "entity_id": rec[8],
                    "entity_name": rec[9],
                }
            )
        return rows

    def vector_query(self, label: str, vector: list[float], k: int = 8) -> list[tuple[str, float]]:
        vec_s = vec_literal(vector)
        try:
            result = self.query(
                f"CALL db.idx.vector.queryNodes('{label}', 'embedding', $k, vecf32({vec_s})) YIELD node, score RETURN node.id, score",
                {"k": k},
                read_only=True,
            )
            return [(rec[0], float(rec[1])) for rec in result.result_set]
        except Exception:
            return []
