from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EntityType = Literal["person", "project", "tool", "org", "topic"]
ClaimKind = Literal["fact", "preference", "constraint", "assumption"]
ClaimStatus = Literal["active", "superseded", "retracted", "suggested"]
DecisionStatus = Literal["active", "stale", "reversed"]


class ExtractedEntity(BaseModel):
    name: str
    type: EntityType
    aliases: list[str] = Field(default_factory=list)


class ExtractedClaim(BaseModel):
    text: str
    kind: ClaimKind
    subject: str
    predicate_key: str
    evidence_msg_idx: int
    confidence: float = 0.7


class ExtractedDecision(BaseModel):
    question: str
    options: list[str] = Field(default_factory=list)
    choice: str
    rationale: str
    assumptions: list[str] = Field(default_factory=list)
    evidence_msg_idx: int


class ExtractedWorkflow(BaseModel):
    name: str
    steps: list[str] = Field(default_factory=list)
    evidence_msg_idx: int = 0


class ExtractionResult(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    claims: list[ExtractedClaim] = Field(default_factory=list)
    decisions: list[ExtractedDecision] = Field(default_factory=list)
    workflows: list[ExtractedWorkflow] = Field(default_factory=list)
