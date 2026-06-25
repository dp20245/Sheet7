from __future__ import annotations

from .schema import ClassifierStatus, EvidenceEvent, SheetRow


TAB_NAMES = ["Evidence", "Signals", "Clusters", "RunLog"]

EVIDENCE_HEADERS = [
    "event_id",
    "run_id",
    "retrieved_at",
    "filing_date",
    "source",
    "country_system",
    "disclosure_layer",
    "company_name",
    "entity_key",
    "company_ids",
    "sector",
    "document_type",
    "source_url",
    "evidence_text",
    "sections_hit",
    "matched_terms",
    "signal_label",
    "candidate_score",
    "candidate_label",
    "candidate_reason",
    "likely_noise",
    "llm_review_status",
    "decay_weight",
    "human_review_status",
    "notes",
]

SIGNALS_HEADERS = [
    "signal_id",
    "event_id",
    "entity_key",
    "company_name",
    "country_system",
    "sector",
    "source",
    "document_type",
    "filing_date",
    "signal_label",
    "intent_type",
    "intent_tense",
    "is_foreign_entering_india",
    "polarity",
    "intent_evidence",
    "intent_confidence",
    "final_score",
    "classifier_status",
    "supersession_status",
    "superseded_by",
    "promotion_reason",
    "judgment_agreement",
    "signal_summary",
    "why_it_matters",
    "suggested_bd_angle",
    "bd_context",
    "why_now",
    "decay_weight",
    "human_review_status",
    "enriched_at",
    "enrichment_model",
    "source_url",
    "notes",
]

CLUSTERS_HEADERS = [
    "cluster_id",
    "entity_key",
    "company_name",
    "country_system",
    "sector",
    "cluster_theme",
    "cluster_summary",
    "evidence_event_ids",
    "signal_ids",
    "signal_count",
    "best_signal_id",
    "latest_filing_date",
    "cluster_score",
    "human_review_status",
    "notes",
]

RUNLOG_HEADERS = [
    "run_id",
    "started_at",
    "finished_at",
    "connector",
    "status",
    "rows_seen",
    "evidence_added",
    "signals_added",
    "llm_calls_made",
    "error",
]


def _dt(value) -> str:
    return value.isoformat(timespec="seconds") if value else ""


def _ids(values: dict[str, str]) -> str:
    return "|".join(f"{k}:{v}" for k, v in sorted(values.items()))


def evidence_row(event: EvidenceEvent) -> SheetRow:
    values = [
        event.event_id,
        event.run_id,
        _dt(event.retrieved_at),
        _dt(event.filing_date),
        event.source,
        event.country_system,
        event.disclosure_layer,
        event.company_name,
        event.entity_key,
        _ids(event.company_ids),
        event.sector,
        event.document_type,
        str(event.source_url),
        event.evidence_text[:40000],  # Sheets hard limit is 50k chars per cell
        "|".join(event.sections_hit),
        "|".join(event.matched_terms),
        event.signal_label,
        str(event.candidate_score),
        event.candidate_label,
        event.candidate_reason,
        str(event.likely_noise).upper(),
        event.llm_review_status,
        f"{event.decay_weight:.4f}",
        event.human_review_status,
        event.notes,
    ]
    return SheetRow(values=values)


def signal_row(event: EvidenceEvent) -> SheetRow | None:
    if event.classifier_status == ClassifierStatus.REJECTED_NOISE:
        return None

    values = [
        f"sig_{event.event_id}",
        event.event_id,
        event.entity_key,
        event.company_name,
        event.country_system,
        event.sector,
        event.source,
        event.document_type,
        _dt(event.filing_date),
        event.signal_label,
        event.intent_type,
        event.intent_tense,
        str(event.is_foreign_entering_india).upper(),
        "neutral",
        event.intent_evidence,
        f"{event.intent_confidence:.2f}",
        str(event.final_score),
        event.classifier_status.value,
        event.supersession_status,
        event.superseded_by,
        event.promotion_reason,
        event.judgment_agreement,
        event.signal_summary,
        event.why_it_matters,
        event.suggested_bd_angle,
        event.bd_context,
        event.why_now,
        f"{event.decay_weight:.4f}",
        event.human_review_status,
        _dt(event.enriched_at),
        event.enrichment_model,
        str(event.source_url),
        event.notes,
    ]
    return SheetRow(values=values)
