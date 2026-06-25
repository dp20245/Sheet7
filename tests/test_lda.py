"""Tests for the LDA connector. Uses the real probe sample, no mocks, no network."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sheet7_pipeline.connectors.lda import _candidate_score, _matched, _parse_filing, _signal_label
from sheet7_pipeline.schema import ClassifierStatus, EvidenceEvent

SAMPLE = Path(__file__).parent.parent / "probe_out" / "lda_sample.json"


def _load_sample() -> dict:
    return json.loads(SAMPLE.read_text())


# ---------------------------------------------------------------------------
# prefilter
# ---------------------------------------------------------------------------

def test_matched_finds_india_terms():
    assert "india" in _matched("Export to India for manufacturing purposes")


def test_matched_finds_china_plus_one():
    assert "nearshoring" in _matched("We are nearshoring production from China")


def test_matched_empty_on_boilerplate():
    assert not _matched("Annual report filing with no geographic specifics")


# ---------------------------------------------------------------------------
# signal_label
# ---------------------------------------------------------------------------

def test_label_china_plus_one():
    matched = {"reshoring", "india"}
    assert _signal_label(matched) == "china_plus_one"


def test_label_policy_lobbying():
    matched = {"india", "tariff"}
    assert _signal_label(matched) == "india_policy_lobbying"


def test_label_investment():
    matched = {"india", "manufacturing"}
    assert _signal_label(matched) == "india_investment"


def test_label_interest_fallback():
    matched = {"india"}
    assert _signal_label(matched) == "india_interest"


# ---------------------------------------------------------------------------
# candidate_score
# ---------------------------------------------------------------------------

def test_score_clamped_to_100():
    # many hits — should not exceed 100
    assert _candidate_score({"india", "nearshoring", "manufacturing", "tariff", "fdi"}, 2026, 5) <= 100


def test_score_recent_beats_old():
    matched = {"india", "manufacturing"}
    recent = _candidate_score(matched, 2026, 2)
    old = _candidate_score(matched, 2020, 2)
    assert recent > old


# ---------------------------------------------------------------------------
# _parse_filing using the real probe sample
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not SAMPLE.exists(), reason="probe_out/lda_sample.json not present")
def test_parse_real_sample_produces_event():
    raw = _load_sample()
    from datetime import UTC, datetime
    ev = _parse_filing(raw, run_id="test_run", retrieved_at=datetime.now(UTC))
    assert ev is not None
    assert isinstance(ev, EvidenceEvent)
    assert ev.source == "lda"
    assert ev.disclosure_layer == "lobbying"
    assert ev.entity_key.startswith("lda:")
    assert ev.evidence_text  # non-empty
    assert ev.matched_terms  # at least one hit
    assert 0 <= ev.candidate_score <= 100
    assert 0 <= ev.decay_weight <= 1.0  # sample is from 2000; decay legitimately approaches 0


@pytest.mark.skipif(not SAMPLE.exists(), reason="probe_out/lda_sample.json not present")
def test_parse_real_sample_one_row_per_filing():
    """One Evidence row for a filing regardless of how many activities it has."""
    raw = _load_sample()
    # add a second activity to the same filing
    raw["lobbying_activities"].append({
        "general_issue_code": "TRD",
        "general_issue_code_display": "Trade (domestic/foreign)",
        "description": "India tariff on steel exports and FDI rules",
        "foreign_entity_issues": None,
        "lobbyists": [],
        "government_entities": [],
    })
    from datetime import UTC, datetime
    ev = _parse_filing(raw, run_id="test_run", retrieved_at=datetime.now(UTC))
    # still one event, evidence_text contains both descriptions stitched
    assert ev is not None
    assert "Export to India" in ev.evidence_text
    assert "India tariff" in ev.evidence_text
    assert len(ev.sections_hit) == 2  # two activities = two section tags


@pytest.mark.skipif(not SAMPLE.exists(), reason="probe_out/lda_sample.json not present")
def test_parse_filing_with_no_matching_terms_returns_none():
    raw = _load_sample()
    for act in raw["lobbying_activities"]:
        act["description"] = "General regulatory compliance update with no geographic focus"
    from datetime import UTC, datetime
    ev = _parse_filing(raw, run_id="test_run", retrieved_at=datetime.now(UTC))
    assert ev is None
