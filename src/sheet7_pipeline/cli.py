from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .classifier import decide
from .ids import event_id
from .schema import ClassifierVote, EvidenceEvent
from .sheets import evidence_row, signal_row


def _load_secrets() -> None:
    secrets = Path(__file__).parent.parent.parent / "SHEET7SECRETS"
    if secrets.exists():
        for line in secrets.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def demo() -> None:
    embedding = ClassifierVote(label="india_investment", score=88)
    zero_shot = ClassifierVote(label="india_investment", score=84)
    decision = decide(embedding, zero_shot, source_reliability_bonus=5)
    event = EvidenceEvent(
        event_id=event_id("sec", "example", "acme", "india_investment"),
        run_id="demo_run",
        retrieved_at=datetime.now(UTC),
        filing_date=datetime(2026, 6, 18, tzinfo=UTC),
        source="sec",
        country_system="US",
        disclosure_layer="filing",
        company_name="Acme Corp",
        entity_key="sec:0000000000",
        company_ids={"cik": "0000000000"},
        sector="energy",
        document_type="10-K",
        source_url="https://www.sec.gov/Archives/edgar/data/0/example.txt",
        evidence_text="Acme Corp plans to expand manufacturing capacity in India as part of its China+1 supply-chain strategy.",
        sections_hit=["Item 1", "Item 7"],
        matched_terms=["India", "manufacturing", "China+1"],
        signal_label=decision.label,
        candidate_score=83,
        candidate_label=decision.label,
        candidate_reason="official filing with India, manufacturing, and China+1 terms",
        intent_type="expansion",
        intent_tense="stated_future",
        is_foreign_entering_india=True,
        intent_evidence="Acme Corp plans to expand manufacturing capacity in India as part of its China+1 supply-chain strategy.",
        intent_confidence=0.86,
        final_score=decision.score,
        classifier_status=decision.status,
        promotion_reason="demo_promoted",
        judgment_agreement="agree",
        signal_summary="Acme describes future India manufacturing expansion.",
        why_it_matters="The filing suggests live India market-entry or expansion intent.",
        suggested_bd_angle="India manufacturing/site-selection advisory.",
        enrichment_model="demo",
    )
    signal = signal_row(event)
    print(json.dumps({"Evidence": evidence_row(event).values, "Signals": signal.values if signal else None}, indent=2))


def run_lda(args: argparse.Namespace) -> None:
    from .connectors.lda import fetch
    from .writer import append_evidence, append_runlog

    run_id = f"lda_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    started_at = datetime.now(UTC)
    print(f"[lda] run_id={run_id}  years_back={args.years_back}  max_pages={args.max_pages}")

    rows: list[EvidenceEvent] = []
    status = "ok"
    error = ""
    try:
        for ev in fetch(run_id=run_id, years_back=args.years_back, max_pages_per_query=args.max_pages):
            rows.append(ev)
            if args.verbose:
                print(f"  [{ev.candidate_score:3d}] {ev.company_name[:50]:<50} {ev.signal_label}")
        print(f"[lda] fetched {len(rows)} rows")

        if not args.dry_run:
            added = append_evidence(rows, verbose=True)
            append_runlog(run_id, started_at, "lda", status, len(rows), added)
            print(f"[lda] done — {added} rows written to Evidence tab")
        else:
            print(f"[lda] dry-run — skipping sheet write")
    except Exception as exc:
        status = "failed"
        error = str(exc)
        print(f"[lda] ERROR: {exc}")
        if not args.dry_run:
            append_runlog(run_id, started_at, "lda", status, len(rows), 0, error)
        raise


def run_sec(args: argparse.Namespace) -> None:
    from .connectors.sec import fetch
    from .writer import append_evidence, append_runlog

    run_id = f"sec_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    started_at = datetime.now(UTC)
    print(f"[sec] run_id={run_id}  start_date={args.start_date}  max_efts_pages={args.max_pages}")

    rows: list[EvidenceEvent] = []
    status = "ok"
    error = ""
    try:
        for ev in fetch(
            run_id=run_id,
            start_date=args.start_date,
            max_efts_pages=args.max_pages,
            verbose=args.verbose,
        ):
            rows.append(ev)
        print(f"[sec] fetched {len(rows)} rows")

        if not args.dry_run:
            added = append_evidence(rows, verbose=True)
            append_runlog(run_id, started_at, "sec", status, len(rows), added)
            print(f"[sec] done — {added} rows written to Evidence tab")
        else:
            print(f"[sec] dry-run — skipping sheet write")
    except Exception as exc:
        status = "failed"
        error = str(exc)
        print(f"[sec] ERROR: {exc}")
        if not args.dry_run:
            append_runlog(run_id, started_at, "sec", status, len(rows), 0, error)
        raise


def run_epo_ops(args: argparse.Namespace) -> None:
    from .connectors.epo_ops import fetch

    run_id = f"epo_ops_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    started_at = datetime.now(UTC)
    print(f"[epo_ops] run_id={run_id}  max_results={args.max_results}")

    rows: list[EvidenceEvent] = []
    status = "ok"
    error = ""
    try:
        for ev in fetch(
            run_id=run_id,
            applicants=args.applicant,
            queries=args.query,
            max_results=args.max_results,
            discovery=not args.no_discovery,
            verbose=args.verbose,
        ):
            rows.append(ev)
            if args.verbose:
                print(f"  [{ev.candidate_score:3d}] {ev.company_name[:50]:<50} {ev.company_ids.get('publication_ref', '')}")
        print(f"[epo_ops] fetched {len(rows)} rows")

        if not args.dry_run:
            from .writer import append_evidence, append_runlog

            added = append_evidence(rows, verbose=True)
            append_runlog(run_id, started_at, "epo_ops", status, len(rows), added)
            print(f"[epo_ops] done — {added} rows written to Evidence tab")
        else:
            print("[epo_ops] dry-run — skipping sheet write")
    except Exception as exc:
        status = "failed"
        error = str(exc)
        print(f"[epo_ops] ERROR: {exc}")
        if not args.dry_run:
            from .writer import append_runlog

            append_runlog(run_id, started_at, "epo_ops", status, len(rows), 0, error)
        raise


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

def main() -> None:
    _load_secrets()

    parser = argparse.ArgumentParser(prog="sheet7")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("demo")

    lda_p = sub.add_parser("run-lda", help="Fetch LDA lobbying disclosures → Evidence tab")
    lda_p.add_argument("--years-back", type=int, default=3)
    lda_p.add_argument("--max-pages", type=int, default=20)
    lda_p.add_argument("--dry-run", action="store_true", help="Fetch but don't write to sheets")
    lda_p.add_argument("--verbose", action="store_true")

    sec_p = sub.add_parser("run-sec", help="Fetch SEC 10-K/20-F filings → Evidence tab")
    sec_p.add_argument("--start-date", default="2024-01-01")
    sec_p.add_argument("--max-pages", type=int, default=2, help="EFTS pages per query")
    sec_p.add_argument("--dry-run", action="store_true", help="Fetch but don't write to sheets")
    sec_p.add_argument("--verbose", action="store_true")

    epo_p = sub.add_parser("run-epo-ops", help="Fetch EPO OPS patent records -> Evidence tab")
    epo_p.add_argument("--applicant", action="append", default=[], help="Applicant/company name; can be repeated")
    epo_p.add_argument("--query", action="append", default=[], help="Raw OPS CQL query; can be repeated")
    epo_p.add_argument("--max-results", type=int, default=100)
    epo_p.add_argument("--no-discovery", action="store_true", help="Skip broad discovery queries; use only --applicant/--query")
    epo_p.add_argument("--dry-run", action="store_true", help="Fetch but don't write to sheets")
    epo_p.add_argument("--verbose", action="store_true")

    rank_p = sub.add_parser("rankings", help="Write Rankings tab from Evidence data")
    rank_p.add_argument("--verbose", action="store_true")

    args = parser.parse_args()
    if args.command == "demo":
        demo()
    elif args.command == "run-lda":
        run_lda(args)
    elif args.command == "run-sec":
        run_sec(args)
    elif args.command == "run-epo-ops":
        run_epo_ops(args)
    elif args.command == "rankings":
        from .writer import write_rankings
        write_rankings(verbose=args.verbose)
        print("[rankings] done")


if __name__ == "__main__":
    main()
