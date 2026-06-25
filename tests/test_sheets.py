from datetime import UTC, datetime

from sheet7_pipeline.schema import ClassifierStatus, EvidenceEvent
from sheet7_pipeline.sheets import EVIDENCE_HEADERS, SIGNALS_HEADERS, TAB_NAMES, evidence_row, signal_row


def test_canonical_tab_and_column_names() -> None:
    assert TAB_NAMES == ["Evidence", "Signals", "Clusters", "RunLog"]
    assert "entity_key" in EVIDENCE_HEADERS
    assert "candidate_score" in EVIDENCE_HEADERS
    assert "entity_key" in SIGNALS_HEADERS
    assert "final_score" in SIGNALS_HEADERS
    assert "cik" not in EVIDENCE_HEADERS


def test_rows_use_entity_key_not_cik_column() -> None:
    event = EvidenceEvent(
        event_id="sec_0000000000_10k_2026",
        run_id="test_run",
        retrieved_at=datetime.now(UTC),
        filing_date=datetime(2026, 6, 20, tzinfo=UTC),
        source="sec",
        country_system="US",
        disclosure_layer="filing",
        company_name="Acme Corp",
        entity_key="sec:0000000000",
        company_ids={"cik": "0000000000"},
        sector="energy",
        document_type="10-K",
        source_url="https://www.sec.gov/Archives/edgar/data/0/example.txt",
        evidence_text="Acme plans India expansion.",
        sections_hit=["Item 1"],
        matched_terms=["India", "expansion"],
        signal_label="india_investment",
        candidate_score=91,
        candidate_label="india_investment",
        final_score=88,
        classifier_status=ClassifierStatus.PROMOTED,
    )

    assert "sec:0000000000" in evidence_row(event).values
    signal = signal_row(event)
    assert signal is not None
    assert "sec:0000000000" in signal.values
