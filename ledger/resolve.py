from __future__ import annotations

from typing import Any

from ledger.embeddings import cosine, embed_text
from ledger.ids import nid
from ledger.llm import complete_json
from ledger.config import extract_model

HIGH = 0.92
LOW = 0.78


def _norm_name(name: str) -> str:
    return " ".join(name.lower().split())


class EntityResolver:
    def __init__(self, store) -> None:
        self.store = store
        self.entities = store.all_entities()

    def resolve(
        self,
        name: str,
        etype: str,
        aliases: list[str] | None = None,
        *,
        embedding: list[float] | None = None,
    ) -> str:
        aliases = aliases or []
        needle = _norm_name(name)
        alias_set = {_norm_name(a) for a in aliases if a}
        if embedding is None:
            embedding = embed_text(name)

        exact = None
        best = None
        best_score = -1.0
        for ent in self.entities:
            if ent["type"] != etype:
                continue
            names = {_norm_name(ent["name"]), *(_norm_name(a) for a in ent.get("aliases") or [])}
            if needle in names or alias_set & names:
                exact = ent
                break
            if ent.get("embedding"):
                score = cosine(embedding, ent["embedding"])
                if score > best_score:
                    best, best_score = ent, score

        if exact:
            chosen = exact
        elif best and best_score >= HIGH:
            chosen = best
        elif best and LOW <= best_score < HIGH and self._llm_same(name, best["name"], etype):
            chosen = best
        else:
            entity_id = nid("entity", etype, needle)
            chosen = {
                "id": entity_id,
                "name": name,
                "type": etype,
                "aliases": aliases,
                "embedding": embedding,
            }
            self.store.upsert_entity(entity_id, name, etype, aliases, embedding)
            self.entities.append(chosen)
            return entity_id

        merged_aliases = list(dict.fromkeys([*(chosen.get("aliases") or []), *aliases, name, chosen["name"]]))
        if name not in merged_aliases:
            merged_aliases.append(name)
        self.store.upsert_entity(chosen["id"], chosen["name"], chosen["type"], merged_aliases, chosen.get("embedding") or embedding)
        chosen["aliases"] = merged_aliases
        return chosen["id"]

    def _llm_same(self, a: str, b: str, etype: str) -> bool:
        try:
            data = complete_json(
                "Answer whether two names refer to the same entity. JSON: {\"same\": true|false}",
                f"type={etype}\nname_a={a}\nname_b={b}",
                model=extract_model(),
            )
            return bool(data.get("same"))
        except Exception:
            return False


def find_entity_id(entities: list[dict[str, Any]], name: str) -> str | None:
    needle = _norm_name(name)
    for ent in entities:
        names = {_norm_name(ent["name"]), *(_norm_name(a) for a in ent.get("aliases") or [])}
        if needle in names:
            return ent["id"]
    return None
