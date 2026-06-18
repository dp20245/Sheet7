from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class ClassifierStatus(StrEnum):
    PROMOTED = "promoted"
    NEEDS_RESEARCH = "needs_research"
    REJECTED_NOISE = "rejected_noise"


SignalLabel = Literal[
    "india_interest",
    "india_investment",
    "india_ip_market_entry",
    "india_entity_spine",
    "china_plus_one",
    "india_policy_lobbying",
    "india_risk_or_friction",
    "chose_competitor_market",
    "boilerplate_or_noise",
]

Polarity = Literal["positive", "negative", "mixed", "neutral"]
Confidence = Literal["low", "medium", "high"]


class ClassifierVote(BaseModel):
    label: SignalLabel
    score: int = Field(ge=0, le=100)


class EvidenceEvent(BaseModel):
    run_date: datetime
    signal_date: datetime | None = None
    event_id: str
    source: str
    country_system: str
    disclosure_layer: str
    company: str
    sectors: list[str] = Field(default_factory=list)
    entity_ids: dict[str, str] = Field(default_factory=dict)
    document_type: str
    source_url: HttpUrl
    evidence_text: str
    matched_terms: list[str] = Field(default_factory=list)
    signal_label: SignalLabel
    polarity: Polarity
    embedding: ClassifierVote
    zero_shot: ClassifierVote
    final_score: int = Field(ge=0, le=100)
    confidence: Confidence
    classifier_status: ClassifierStatus


class SheetRow(BaseModel):
    values: list[str]

