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
    "china_plus_one",
    "india_policy_lobbying",
    "india_risk_or_friction",
    "chose_competitor_market",
    "boilerplate_or_noise",
]

IntentType = Literal[
    "market_entry",
    "expansion",
    "diversification",
    "supply_chain_shift",
    "regulatory_positioning",
    "ip_market_entry",
    "none",
]
IntentTense = Literal[
    "stated_future",
    "in_progress",
    "completed",
    "speculated_by_third_party",
    "unclear",
    "none",
]
Polarity = Literal["positive", "negative", "mixed", "neutral"]
Confidence = Literal["low", "medium", "high"]
HumanReviewStatus = Literal["unreviewed", "confirmed", "rejected"]
LLMReviewStatus = Literal["pending", "sent", "reviewed", "skipped"]
SupersessionStatus = Literal["current", "superseded"]
JudgmentAgreement = Literal["agree", "disagree", ""]


class ClassifierVote(BaseModel):
    label: SignalLabel
    score: int = Field(ge=0, le=100)


class EvidenceEvent(BaseModel):
    event_id: str
    run_id: str
    retrieved_at: datetime
    filing_date: datetime | None = None
    source: str
    country_system: str
    disclosure_layer: str
    company_name: str
    entity_key: str
    company_ids: dict[str, str] = Field(default_factory=dict)
    sector: str = ""
    document_type: str
    source_url: HttpUrl
    evidence_text: str
    sections_hit: list[str] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    signal_label: SignalLabel
    candidate_score: int = Field(ge=0, le=100)
    candidate_label: SignalLabel
    candidate_reason: str = ""
    likely_noise: bool = False
    llm_review_status: LLMReviewStatus = "pending"
    decay_weight: float = Field(default=1.0, ge=0)
    human_review_status: HumanReviewStatus = "unreviewed"
    notes: str = ""

    intent_type: IntentType = "none"
    intent_tense: IntentTense = "none"
    is_foreign_entering_india: bool = False
    intent_evidence: str = ""
    intent_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    final_score: int = Field(default=0, ge=0, le=100)
    classifier_status: ClassifierStatus = ClassifierStatus.NEEDS_RESEARCH
    supersession_status: SupersessionStatus = "current"
    superseded_by: str = ""
    promotion_reason: str = ""
    judgment_agreement: JudgmentAgreement = ""
    signal_summary: str = ""
    why_it_matters: str = ""
    suggested_bd_angle: str = ""
    bd_context: str = ""
    why_now: str = ""
    enriched_at: datetime | None = None
    enrichment_model: str = ""


class SheetRow(BaseModel):
    values: list[str]
