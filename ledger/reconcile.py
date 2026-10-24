from __future__ import annotations

from ledger.config import adjudicate_model
from ledger.embeddings import cosine
from ledger.llm import complete_json


def adjudicate_claim(new_text: str, old_text: str, predicate_key: str) -> str:
    """Return same | supersedes | contradicts | unrelated | retracts."""
    try:
        data = complete_json(
            "Compare two claims that share a predicate. "
            "Return JSON {\"relation\": one of same, supersedes, contradicts, unrelated, retracts}. "
            "supersedes = the new claim updates the old one. retracts = user said ignore the old claim.",
            f"predicate_key={predicate_key}\nOLD: {old_text}\nNEW: {new_text}",
            model=adjudicate_model(),
        )
        rel = str(data.get("relation") or "unrelated").lower()
        if rel in {"same", "supersedes", "contradicts", "unrelated", "retracts"}:
            return rel
    except Exception:
        pass
    if cosine_fallback(new_text, old_text) >= 0.93:
        return "same"
    return "unrelated"


def cosine_fallback(a: str, b: str) -> float:
    from ledger.embeddings import embed_text

    return cosine(embed_text(a), embed_text(b))


def propagate_staleness(store) -> list[dict]:
    result = store.query(
        """
        MATCH (d:Decision)
        WHERE d.status = 'active'
        MATCH (d)-[:DEPENDS_ON]->(c:Claim)
        WHERE c.status IN ['superseded', 'retracted']
        OPTIONAL MATCH (n:Claim)-[:SUPERSEDES]->(c)
        RETURN d.id, d.question, d.choice, c.id, c.text, n.id, n.text
        """,
        read_only=True,
    )
    flagged = []
    for rec in result.result_set:
        decision_id, question, choice, claim_id, claim_text, new_id, new_text = rec
        reason = f"Assumption '{claim_text}' is {('superseded by ' + (new_text or '')) if new_id else 'no longer active'}."
        store.mark_stale(decision_id, reason)
        flagged.append(
            {
                "decision_id": decision_id,
                "question": question,
                "choice": choice,
                "broken_claim_id": claim_id,
                "broken_claim": claim_text,
                "superseding_claim_id": new_id,
                "stale_reason": reason,
            }
        )
    return flagged
