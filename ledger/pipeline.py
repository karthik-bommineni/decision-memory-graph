from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ledger.adapters.claude import write_jsonl
from ledger.config import DEFAULT_CLAUDE_EXPORT, NORMALIZED_DIR
from ledger.embeddings import embed_text, embed_texts, cosine
from ledger.extract import extract_conversation
from ledger.graph_store import GraphStore
from ledger.ids import message_id, nid
from ledger.reconcile import adjudicate_claim, propagate_staleness
from ledger.redact import redact_jsonl
from ledger.resolve import EntityResolver


def normalize_claude(
    input_path: Path | None = None,
    output_path: Path | None = None,
    *,
    limit: int | None = None,
    title_contains: str | None = None,
) -> Path:
    src = input_path or DEFAULT_CLAUDE_EXPORT
    dst = output_path or (NORMALIZED_DIR / "claude.jsonl")
    n = write_jsonl(src, dst, limit=limit, title_contains=title_contains)
    print(f"Normalized {n} conversations -> {dst}")
    return dst


def redact_file(input_path: Path, output_path: Path | None = None) -> Path:
    dst = output_path or input_path.with_name(input_path.stem + ".redacted.jsonl")
    n = redact_jsonl(input_path, dst)
    print(f"Redacted {n} conversations -> {dst}")
    return dst


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    rows.sort(key=lambda c: c.get("started_at") or "")
    return rows


def ingest_jsonl(path: Path, store: GraphStore | None = None) -> int:
    store = store or GraphStore()
    store.ensure_schema()
    convs = load_jsonl(path)
    for conv in convs:
        texts = [m.get("text") or "" for m in conv.get("messages") or []]
        vecs = embed_texts(texts) if texts else []
        store.upsert_conversation(conv, vecs)
        title = str(conv.get("title") or "")
        safe_title = title.encode("ascii", "replace").decode("ascii")
        print(f"  loaded {safe_title} ({len(texts)} messages)")
    print(f"Ingested {len(convs)} conversations into graph {store.name}")
    return len(convs)


def _match_assumption(
    store: GraphStore,
    text: str,
    entity_id: str | None,
    *,
    embedding: list[float] | None = None,
) -> str:
    if embedding is None:
        embedding = embed_text(text)
    best_id = None
    best = 0.0
    for claim in store.active_claims():
        if not claim.get("embedding"):
            continue
        score = cosine(embedding, claim["embedding"])
        if score > best:
            best, best_id = score, claim["id"]
    if best_id and best >= 0.82:
        return best_id
    claim_id = nid("claim", "assumption", text)
    store.upsert_claim(
        {
            "id": claim_id,
            "text": text,
            "kind": "assumption",
            "predicate_key": "assumption",
            "status": "active",
            "valid_from": "",
            "confidence": 0.6,
            "embedding": embedding,
        }
    )
    if entity_id:
        store.relate_about("Claim", claim_id, entity_id)
    return claim_id


def extract_into_graph(path: Path, store: GraphStore | None = None, *, limit: int | None = None) -> dict[str, int]:
    store = store or GraphStore()
    store.ensure_schema()
    resolver = EntityResolver(store)
    convs = load_jsonl(path)
    if limit is not None:
        convs = convs[:limit]
    counts = {"entities": 0, "claims": 0, "decisions": 0, "stale": 0}
    for conv in convs:
        title = str(conv.get("title") or "")
        n_msgs = len(conv.get("messages") or [])
        print(f"Extracting: {title.encode('ascii', 'replace').decode('ascii')} ({n_msgs} msgs)", flush=True)
        try:
            result = extract_conversation(conv)
        except Exception as exc:
            print(f"  skipped conversation: {exc}")
            continue
        entity_ids: dict[str, str] = {}
        extra_subjects = [
            c.subject
            for c in result.claims
            if c.subject and c.subject.lower() not in {e.name.lower() for e in result.entities}
        ]
        name_texts = [e.name for e in result.entities] + extra_subjects
        claim_texts = [c.text for c in result.claims]
        dec_texts = [f"{d.question} {d.choice}" for d in result.decisions]
        wf_texts = [wf.name + " " + " ".join(wf.steps) for wf in result.workflows]
        assumption_texts = [a for d in result.decisions for a in d.assumptions]
        packed = name_texts + claim_texts + dec_texts + wf_texts + assumption_texts
        print(
            f"  embedding {len(packed)} strings in batches "
            f"({len(result.entities)} entities, {len(result.claims)} claims, "
            f"{len(result.decisions)} decisions)",
            flush=True,
        )
        packed_vecs = embed_texts(packed) if packed else []
        n_names = len(name_texts)
        n_claims = len(claim_texts)
        n_decs = len(dec_texts)
        name_vecs = packed_vecs[:n_names]
        claim_vecs = packed_vecs[n_names : n_names + n_claims]
        dec_vecs = packed_vecs[n_names + n_claims : n_names + n_claims + n_decs]
        wf_vecs = packed_vecs[
            n_names + n_claims + n_decs : n_names + n_claims + n_decs + len(wf_texts)
        ]
        assumption_vecs = packed_vecs[n_names + n_claims + n_decs + len(wf_texts) :]
        name_vec_by_lower = {
            text.lower(): vec for text, vec in zip(name_texts, name_vecs)
        }

        for i, ent in enumerate(result.entities):
            eid = resolver.resolve(
                ent.name, ent.type, ent.aliases, embedding=name_vecs[i]
            )
            entity_ids[ent.name.lower()] = eid
            counts["entities"] += 1

        print(f"  writing {len(result.claims)} claims", flush=True)
        for claim, embedding in zip(result.claims, claim_vecs):
            subject_id = entity_ids.get(claim.subject.lower())
            if subject_id is None and claim.subject:
                subject_id = resolver.resolve(
                    claim.subject,
                    "topic",
                    [],
                    embedding=name_vec_by_lower.get(claim.subject.lower()),
                )
            relation = "unrelated"
            matched = None
            for existing in store.active_claims():
                if existing.get("predicate_key") != claim.predicate_key:
                    continue
                if subject_id and existing.get("entity_id") and existing["entity_id"] != subject_id:
                    continue
                relation = adjudicate_claim(claim.text, existing["text"], claim.predicate_key)
                if relation != "unrelated":
                    matched = existing
                    break

            status = "active"
            if relation == "same" and matched:
                continue
            if relation in {"supersedes", "contradicts"} and matched:
                if float(claim.confidence) < 0.55:
                    status = "suggested"
                else:
                    status = "active"
            if "ignore" in claim.text.lower() or "forget that" in claim.text.lower():
                relation = "retracts"

            claim_id = nid("claim", conv["conv_id"], str(claim.evidence_msg_idx), claim.predicate_key, claim.text[:80])
            store.upsert_claim(
                {
                    "id": claim_id,
                    "text": claim.text,
                    "kind": claim.kind,
                    "predicate_key": claim.predicate_key,
                    "status": "suggested" if status == "suggested" else "active",
                    "valid_from": conv.get("started_at") or "",
                    "confidence": claim.confidence,
                    "embedding": embedding,
                }
            )
            mid = message_id(conv.get("source") or "claude", conv["conv_id"], claim.evidence_msg_idx)
            store.relate_extracted("Claim", claim_id, mid)
            if subject_id:
                store.relate_about("Claim", claim_id, subject_id)
            if matched and relation in {"supersedes", "contradicts"} and status == "active":
                store.relate_supersedes("Claim", claim_id, matched["id"])
                store.set_claim_status(matched["id"], "superseded", conv.get("started_at") or "")
            if matched and relation == "retracts":
                store.set_claim_status(matched["id"], "retracted", conv.get("started_at") or "")
            counts["claims"] += 1

        assume_i = 0
        for dec, embedding in zip(result.decisions, dec_vecs):
            dec_id = nid("decision", conv["conv_id"], dec.question, dec.choice)
            store.upsert_decision(
                {
                    "id": dec_id,
                    "question": dec.question,
                    "choice": dec.choice,
                    "options": dec.options,
                    "rationale": dec.rationale,
                    "decided_at": conv.get("started_at") or "",
                    "status": "active",
                    "embedding": embedding,
                }
            )
            mid = message_id(conv.get("source") or "claude", conv["conv_id"], dec.evidence_msg_idx)
            store.relate_extracted("Decision", dec_id, mid)
            about = None
            if entity_ids:
                about = next(iter(entity_ids.values()))
                store.relate_about("Decision", dec_id, about)
            for assumption in dec.assumptions:
                cid = _match_assumption(
                    store, assumption, about, embedding=assumption_vecs[assume_i]
                )
                assume_i += 1
                store.relate_depends(dec_id, cid)
            counts["decisions"] += 1

        for wf, embedding in zip(result.workflows, wf_vecs):
            existing = store.query(
                "MATCH (w:Workflow) RETURN w.id, w.name, w.times_seen, w.embedding_json",
                read_only=True,
            )
            matched_wf = None
            for rec in existing.result_set:
                from ledger.embeddings import cosine as cos
                import json as _json

                score = cos(embedding, _json.loads(rec[3] or "[]") or embedding)
                if score >= 0.88:
                    matched_wf = rec
                    break
            if matched_wf:
                store.query(
                    "MATCH (w:Workflow {id:$id}) SET w.times_seen = w.times_seen + 1",
                    {"id": matched_wf[0]},
                )
            else:
                wf_id = nid("workflow", wf.name)
                store.upsert_workflow(
                    {
                        "id": wf_id,
                        "name": wf.name,
                        "steps": wf.steps,
                        "times_seen": 1,
                        "embedding": embedding,
                    }
                )
                mid = message_id(conv.get("source") or "claude", conv["conv_id"], wf.evidence_msg_idx)
                store.relate_extracted("Workflow", wf_id, mid)

        stale = propagate_staleness(store)
        counts["stale"] += len(stale)
    print(counts)
    return counts
