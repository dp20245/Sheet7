from __future__ import annotations

from .schema import EvidenceEvent, SheetRow


EVIDENCE_HEADERS = [
    "Run Date",
    "Signal Date",
    "Event ID",
    "Source",
    "Country/System",
    "Disclosure Layer",
    "Company",
    "Sector(s)",
    "Entity IDs",
    "Document Type",
    "Source URL",
    "Evidence Text",
    "Matched Terms",
    "Signal Label",
    "Polarity",
    "Embedding Label",
    "Embedding Score",
    "Zero-Shot Label",
    "Zero-Shot Score",
    "Final Score",
    "Confidence",
    "Classifier Status",
]

SIGNALS_HEADERS = [
    "Signal Date",
    "Company",
    "Sector(s)",
    "Country/System",
    "Source",
    "Disclosure Layer",
    "Signal Label",
    "Polarity",
    "Final Score",
    "Confidence",
    "India/China+1 Thesis",
    "Evidence Snippet",
    "Source URL",
    "Classifier Status",
    "Event ID",
]


def evidence_row(event: EvidenceEvent) -> SheetRow:
    values = [
        event.run_date.isoformat(timespec="seconds"),
        event.signal_date.isoformat(timespec="seconds") if event.signal_date else "",
        event.event_id,
        event.source,
        event.country_system,
        event.disclosure_layer,
        event.company,
        ", ".join(event.sectors),
        "; ".join(f"{k}:{v}" for k, v in sorted(event.entity_ids.items())),
        event.document_type,
        str(event.source_url),
        event.evidence_text,
        ", ".join(event.matched_terms),
        event.signal_label,
        event.polarity,
        event.embedding.label,
        str(event.embedding.score),
        event.zero_shot.label,
        str(event.zero_shot.score),
        str(event.final_score),
        event.confidence,
        event.classifier_status.value,
    ]
    return SheetRow(values=values)


def signal_row(event: EvidenceEvent) -> SheetRow | None:
    if event.classifier_status.value == "rejected_noise":
        return None

    snippet = event.evidence_text[:500]
    thesis = f"{event.signal_label.replace('_', ' ')}: {snippet[:180]}"
    values = [
        event.signal_date.isoformat(timespec="seconds") if event.signal_date else "",
        event.company,
        ", ".join(event.sectors),
        event.country_system,
        event.source,
        event.disclosure_layer,
        event.signal_label,
        event.polarity,
        str(event.final_score),
        event.confidence,
        thesis,
        snippet,
        str(event.source_url),
        event.classifier_status.value,
        event.event_id,
    ]
    return SheetRow(values=values)

