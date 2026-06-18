from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from .classifier import decide
from .ids import event_id
from .schema import ClassifierVote, EvidenceEvent
from .sheets import evidence_row, signal_row


def demo() -> None:
    embedding = ClassifierVote(label="india_investment", score=88)
    zero_shot = ClassifierVote(label="india_investment", score=84)
    decision = decide(embedding, zero_shot, source_reliability_bonus=5)
    event = EvidenceEvent(
        run_date=datetime.now(UTC),
        signal_date=datetime(2026, 6, 18, tzinfo=UTC),
        event_id=event_id("sec", "example", "acme", "india_investment"),
        source="sec",
        country_system="US",
        disclosure_layer="company_disclosure",
        company="Acme Corp",
        sectors=["Energy"],
        entity_ids={"CIK": "0000000000"},
        document_type="10-K",
        source_url="https://www.sec.gov/Archives/edgar/data/0/example.txt",
        evidence_text="Acme Corp plans to expand manufacturing capacity in India as part of its China+1 supply-chain strategy.",
        matched_terms=["India", "manufacturing", "China+1"],
        signal_label=decision.label,
        polarity="positive",
        embedding=embedding,
        zero_shot=zero_shot,
        final_score=decision.score,
        confidence=decision.confidence,
        classifier_status=decision.status,
    )
    print(json.dumps({"evidence": evidence_row(event).values, "signal": signal_row(event).values}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="sheet7")
    parser.add_argument("command", choices=["demo"])
    args = parser.parse_args()
    if args.command == "demo":
        demo()


if __name__ == "__main__":
    main()

