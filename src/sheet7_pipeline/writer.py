"""Google Sheets writer for Sheet7 pipeline.

Appends Evidence rows without overwriting human_review_status or notes.
Deduplicates by event_id before appending.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from .schema import EvidenceEvent
from .sheets import EVIDENCE_HEADERS, RUNLOG_HEADERS, TAB_NAMES, evidence_row

if TYPE_CHECKING:
    pass

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _creds() -> Credentials:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON not set")
    info = json.loads(raw)
    return Credentials.from_service_account_info(info, scopes=SCOPES)


def _service():
    return build("sheets", "v4", credentials=_creds(), cache_discovery=False)


def _spreadsheet_id() -> str:
    sid = os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID", "")
    if not sid:
        raise RuntimeError("GOOGLE_SHEETS_SPREADSHEET_ID not set")
    return sid


def _ensure_tab(svc, sid: str, tab: str) -> None:
    """Create the sheet tab if it doesn't exist."""
    meta = svc.spreadsheets().get(spreadsheetId=sid).execute()
    existing = {s["properties"]["title"] for s in meta.get("sheets", [])}
    if tab not in existing:
        svc.spreadsheets().batchUpdate(
            spreadsheetId=sid,
            body={"requests": [{"addSheet": {"properties": {"title": tab}}}]},
        ).execute()


def _ensure_headers(svc, sid: str, tab: str, headers: list[str]) -> None:
    """Create tab if missing, then write headers to row 1 if empty."""
    _ensure_tab(svc, sid, tab)
    result = svc.spreadsheets().values().get(
        spreadsheetId=sid, range=f"{tab}!A1:A1"
    ).execute()
    if not result.get("values"):
        svc.spreadsheets().values().update(
            spreadsheetId=sid,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            body={"values": [headers]},
        ).execute()


def _existing_event_ids(svc, sid: str) -> set[str]:
    """Read column A of Evidence tab to get all existing event_ids."""
    result = svc.spreadsheets().values().get(
        spreadsheetId=sid, range="Evidence!A:A"
    ).execute()
    rows = result.get("values", [])
    # skip header row
    return {r[0] for r in rows[1:] if r}


def append_evidence(events: list[EvidenceEvent], *, verbose: bool = False) -> int:
    """Append new Evidence rows, skipping already-present event_ids. Returns count added."""
    if not events:
        return 0

    svc = _service()
    sid = _spreadsheet_id()

    _ensure_headers(svc, sid, "Evidence", EVIDENCE_HEADERS)
    existing = _existing_event_ids(svc, sid)

    new_rows = []
    for ev in events:
        if ev.event_id in existing:
            continue
        new_rows.append(evidence_row(ev).values)

    if not new_rows:
        if verbose:
            print(f"  [writer] all {len(events)} rows already present, nothing to append")
        return 0

    svc.spreadsheets().values().append(
        spreadsheetId=sid,
        range="Evidence!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": new_rows},
    ).execute()

    if verbose:
        print(f"  [writer] appended {len(new_rows)} new rows ({len(events) - len(new_rows)} dupes skipped)")
    return len(new_rows)


def write_rankings(*, verbose: bool = False) -> None:
    """Write Rankings tab: top companies by score and by recency."""
    svc = _service()
    sid = _spreadsheet_id()
    _ensure_tab(svc, sid, "Rankings")

    result = svc.spreadsheets().values().get(
        spreadsheetId=sid, range="Evidence!A:Z"
    ).execute()
    rows = result.get("values", [])
    if len(rows) < 2:
        if verbose:
            print("  [rankings] Evidence tab empty, nothing to rank")
        return

    headers = rows[0]
    col = {h: i for i, h in enumerate(headers)}
    data = rows[1:]

    def get(row, name):
        i = col.get(name)
        return row[i] if i is not None and i < len(row) else ""

    # one row per company_name: keep highest score entry
    best: dict[str, list] = {}
    for row in data:
        name = get(row, "company_name")
        score_str = get(row, "candidate_score")
        try:
            score = int(score_str)
        except (ValueError, TypeError):
            score = 0
        if name not in best or score > int(best[name][col["candidate_score"]]):
            best[name] = row

    companies = list(best.values())

    by_score = sorted(companies, key=lambda r: int(get(r, "candidate_score") or 0), reverse=True)
    by_date  = sorted(companies, key=lambda r: get(r, "filing_date"), reverse=True)

    def rank_rows(ranked, rank_label):
        out = [[rank_label, "company_name", "source", "candidate_score", "filing_date", "signal_label"]]
        for i, row in enumerate(ranked, 1):
            out.append([
                str(i),
                get(row, "company_name"),
                get(row, "source"),
                get(row, "candidate_score"),
                get(row, "filing_date")[:10] if get(row, "filing_date") else "",
                get(row, "signal_label"),
            ])
        return out

    score_block = rank_rows(by_score, "rank_by_score")
    date_block  = rank_rows(by_date,  "rank_by_recency")
    # two lists side by side with a blank column between
    gap = [""] * 6
    combined = []
    for i in range(max(len(score_block), len(date_block))):
        left  = score_block[i] if i < len(score_block) else [""] * 6
        right = date_block[i]  if i < len(date_block)  else [""] * 6
        combined.append(left + [""] + right)

    svc.spreadsheets().values().clear(spreadsheetId=sid, range="Rankings!A:M").execute()
    svc.spreadsheets().values().update(
        spreadsheetId=sid,
        range="Rankings!A1",
        valueInputOption="RAW",
        body={"values": combined},
    ).execute()
    if verbose:
        print(f"  [rankings] wrote {len(by_score)} companies × 2 lists")


def append_runlog(
    run_id: str,
    started_at: datetime,
    connector: str,
    status: str,
    rows_seen: int,
    evidence_added: int,
    error: str = "",
) -> None:
    """Append one row to RunLog."""
    svc = _service()
    sid = _spreadsheet_id()
    _ensure_headers(svc, sid, "RunLog", RUNLOG_HEADERS)
    row = [
        run_id,
        started_at.isoformat(timespec="seconds"),
        datetime.now(UTC).isoformat(timespec="seconds"),
        connector,
        status,
        str(rows_seen),
        str(evidence_added),
        "0",   # signals_added — Layer B not wired yet
        "0",   # llm_calls_made
        error[:500] if error else "",
    ]
    svc.spreadsheets().values().append(
        spreadsheetId=sid,
        range="RunLog!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()
