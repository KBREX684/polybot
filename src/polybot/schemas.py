from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class MarketCandidate(BaseModel):
    market_id: str
    question: str
    market_prob: float = Field(ge=0.0, le=1.0)
    liquidity_usdc: float = Field(ge=0.0)
    spread: float = Field(ge=0.0)
    end_time: datetime
    outcomes: list[str] = Field(default_factory=list)

    @property
    def hours_to_end(self) -> float:
        now = datetime.now(tz=timezone.utc)
        return (self.end_time - now).total_seconds() / 3600.0


class EvidenceItem(BaseModel):
    evidence_id: str
    source: str
    published_at: datetime
    text: str
    quality_score: float = Field(ge=0.0, le=1.0)


class GraphEdge(BaseModel):
    from_id: str
    to_id: str
    relation: Literal["supports", "contradicts", "causes", "time_precedes", "depends_on"]
    signed_weight: float = Field(ge=-1.0, le=1.0)


class EvidencePack(BaseModel):
    query: str
    items: list[EvidenceItem] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    contradiction_score: float = Field(ge=0.0, le=1.0, default=0.0)


class GeneratorOutput(BaseModel):
    market_id: str
    side: Literal["BUY_YES", "BUY_NO", "NO_TRADE"]
    fair_prob: float = Field(ge=0.0, le=1.0)
    market_prob: float = Field(ge=0.0, le=1.0)
    edge_raw: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_paths: list[str] = Field(min_length=1)
    key_assumptions: list[str] = Field(default_factory=list)
    invalidation_triggers: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class DiscriminatorOutput(BaseModel):
    verdict: Literal["accept", "reject", "revise"]
    edge_adjustment: float = Field(ge=-1.0, le=1.0)
    rejected_edges: list[str] = Field(default_factory=list)
    logic_flaws: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    final_edge: float = Field(ge=-1.0, le=1.0)
    final_confidence: float = Field(ge=0.0, le=1.0)


class RiskDecision(BaseModel):
    passed: bool
    blocked_rules: list[str] = Field(default_factory=list)
    kelly_fraction: float = Field(ge=0.0, le=1.0, default=0.0)
    suggested_size_usdc: float = Field(ge=0.0, default=0.0)
    reason: str = ""


class TradeIntent(BaseModel):
    market_id: str
    side: Literal["BUY_YES", "BUY_NO"]
    limit_price: float = Field(ge=0.0, le=1.0)
    size_usdc: float = Field(gt=0.0)
    reason_code: str


class DecisionRecord(BaseModel):
    timestamp: datetime
    market_id: str
    question: str
    filter_passed: bool
    filter_reasons: list[str]
    generator_output: dict
    discriminator_output: dict
    risk_decision: dict
    executed_trade: dict | None = None

    @model_validator(mode="before")
    @classmethod
    def default_timestamp(cls, data: dict) -> dict:
        if "timestamp" not in data:
            data["timestamp"] = datetime.now(tz=timezone.utc)
        return data
