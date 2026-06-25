"""LDA connector — fetches US lobbying disclosures and yields EvidenceEvent rows.

One Evidence row per filing (Build Spec §2.1 granularity rule).
All lobbying_activities descriptions are stitched into a single evidence_text.
"""
from __future__ import annotations

import math
import os
import time
from datetime import UTC, datetime
from typing import Iterator

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..ids import event_id as make_event_id
from ..schema import EvidenceEvent, SignalLabel

LDA_BASE = "https://lda.senate.gov/api/v1/filings/"
PAGE_SIZE = 100

# Broad queries submitted to LDA's filing_specific_lobbying_issues filter.
# Local prefilter below then confirms each hit.
_SEARCH_QUERIES = [
    "India",
    "Bharat",
    "Indo-Pacific",
    "China plus one",
    "supply chain divers",
    "reshoring",
    "nearshoring",
    "friendshoring",
]

# Keyword sets from Build Spec §3
_INDIA = frozenset({"india", "indian", "bharat", "south asia", "indo-pacific"})
_CHINA1 = frozenset({
    "china+1", "china plus one", "supply chain diversification",
    "supply-chain resilience", "derisking", "de-risking", "friendshoring",
    "nearshoring", "reshoring", "relocation", "manufacturing shift",
    "production transfer", "supplier concentration", "alternative geographies",
    "non-china sourcing",
})
# ponytail: "branch" and "office" omitted — in LDA text they almost always mean
# "legislative branch" / "congressional office", not a company subsidiary.
_ACTION = frozenset({
    "invest", "investment", "capex", "expand", "expansion", "new facility",
    "plant", "factory", "manufacturing", "production base", "subsidiary",
    "regional hub", "acquisition", "joint venture",
    "mou", "restructuring", "evaluating", "planning", "entering", "launching",
})
_POLICY = frozenset({
    "tariff", "customs", "market access", "trade", "export controls",
    "sanctions", "fdi", "data localization", "telecom", "pharma",
    "medical devices", "defence", "defense", "semiconductors",
    "energy", "infrastructure", "tax treaty",
})
_ALL = _INDIA | _CHINA1 | _ACTION | _POLICY

_ISSUE_CODE_TO_SECTOR = {
    "TRD": "trade", "TAX": "tax", "DEF": "defense", "HCR": "pharma",
    "ENR": "energy", "TEC": "tech", "FIN": "finance",
}
_COUNTRY_MAP = {"US": "US", "GB": "UK", "JP": "JP", "DE": "EU", "FR": "EU", "CA": "CA"}


def _matched(text: str) -> set[str]:
    low = text.lower()
    return {t for t in _ALL if t in low}


def _signal_label(matched: set[str]) -> SignalLabel:
    if matched & _CHINA1:
        return "china_plus_one"
    if matched & _POLICY:
        return "india_policy_lobbying"
    if matched & _ACTION:
        return "india_investment"
    return "india_interest"


def _recency_score(filing_year: int) -> int:
    age = max(0, datetime.now().year - filing_year)
    return max(0, 10 - age * 2)


def _candidate_score(matched: set[str], filing_year: int, n_activities: int) -> int:
    source_rel = 15  # lobbying < 10-K filing (25), > IP (10) per Build Spec §5.1
    company_res = 10  # numeric client_id available
    india_rel = min(20, len(matched & (_INDIA | _CHINA1)) * 5)
    action = min(25, len(matched & _ACTION) * 4 + len(matched & _POLICY) * 3)
    recency = _recency_score(filing_year)
    local_signal = 5 if n_activities > 1 else 2
    return min(100, source_rel + company_res + india_rel + action + recency + local_signal)


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=4, max=60))
def _get_page(client: httpx.Client, params: dict) -> dict:
    r = client.get(LDA_BASE, params=params, timeout=30)
    if r.status_code == 429:
        time.sleep(60)  # LDA rate-limit window; tenacity will retry after
    r.raise_for_status()
    return r.json()


def _parse_filing(filing: dict, run_id: str, retrieved_at: datetime) -> EvidenceEvent | None:
    activities = filing.get("lobbying_activities", [])
    if not activities:
        return None

    # Stitch all activity descriptions into one evidence_text, section-tagged by issue code.
    # ponytail: LDA has no filing sections like 10-K Items; issue codes are the equivalent.
    windows: list[str] = []
    issue_codes: list[str] = []
    for act in activities:
        desc = (act.get("description") or "").strip()
        if not desc:
            continue
        label = act.get("general_issue_code_display") or act.get("general_issue_code") or "Issue"
        windows.append(f"[{label}] {desc}")
        code = act.get("general_issue_code") or ""
        if code:
            issue_codes.append(code)

    if not windows:
        return None

    evidence_text = " ".join(windows)
    # ponytail: match against raw descriptions only, not headers like "[Trade (domestic/foreign)]"
    matched = _matched(" ".join(act.get("description") or "" for act in activities))
    if not matched:
        return None
    if not (matched & _INDIA):
        return None  # no India/Bharat/Indo-Pacific term in description text

    client_obj = filing.get("client", {})
    registrant_obj = filing.get("registrant", {})
    client_name = (client_obj.get("name") or "Unknown").title()
    client_id = client_obj.get("client_id") or client_obj.get("id", "0")
    country_code = client_obj.get("ppb_country") or client_obj.get("country") or "US"

    filing_year = filing.get("filing_year") or retrieved_at.year
    dt_posted = filing.get("dt_posted")
    filing_date: datetime | None = None
    if dt_posted:
        try:
            filing_date = datetime.fromisoformat(dt_posted)
        except ValueError:
            pass

    age_days = (retrieved_at.date() - (filing_date.date() if filing_date else retrieved_at.date())).days
    decay = round(math.exp(-max(0, age_days) / 180), 4)

    eid = make_event_id("lda", str(client_id), str(filing_year), filing.get("filing_period") or "")
    signal_label = _signal_label(matched)
    score = _candidate_score(matched, filing_year, len(activities))
    if score < 50:
        return None

    # Prefer the human-readable filing document URL; fall back to API URL.
    source_url = (
        filing.get("filing_document_url")
        or filing.get("url")
        or f"https://lda.senate.gov/filings/public/filing/{filing.get('filing_uuid', '')}/"
    )

    sector = next((_ISSUE_CODE_TO_SECTOR[c] for c in issue_codes if c in _ISSUE_CODE_TO_SECTOR), "other")

    return EvidenceEvent(
        event_id=eid,
        run_id=run_id,
        retrieved_at=retrieved_at,
        filing_date=filing_date,
        source="lda",
        country_system=_COUNTRY_MAP.get(country_code, country_code or "US"),
        disclosure_layer="lobbying",
        company_name=client_name,
        entity_key=f"lda:{client_id}",
        company_ids={
            "lda_client_id": str(client_id),
            "lda_registrant_id": str(registrant_obj.get("id", "")),
        },
        sector=sector,
        document_type=f"LDA-{filing.get('filing_type', 'LD')}",
        source_url=source_url,  # type: ignore[arg-type]
        evidence_text=evidence_text,
        sections_hit=[w.split("]")[0].lstrip("[") for w in windows],
        matched_terms=sorted(matched),
        signal_label=signal_label,
        candidate_score=score,
        candidate_label=signal_label,
        candidate_reason=f"{len(matched)} matched terms across {len(activities)} lobbying activities",
        likely_noise=score < 20,
        decay_weight=decay,
    )


def fetch(
    run_id: str,
    *,
    years_back: int = 3,
    max_pages_per_query: int = 20,
    api_key: str | None = None,
) -> Iterator[EvidenceEvent]:
    """Yield EvidenceEvent rows for recent LDA filings with India/China+1 lobbying intent.

    Deduplicates by filing_uuid across search queries.
    """
    api_key = api_key or os.environ.get("LDA_API_KEY")
    headers: dict[str, str] = {"User-Agent": os.environ.get("SEC_USER_AGENT", "TAG-Sheet7/0.1")}
    if api_key:
        headers["Authorization"] = f"Token {api_key}"

    start_year = datetime.now().year - years_back
    seen: set[str] = set()
    retrieved_at = datetime.now(UTC)

    with httpx.Client(headers=headers) as client:
        for query in _SEARCH_QUERIES:
            page_num = 1
            while page_num <= max_pages_per_query:
                params: dict[str, object] = {
                    "filing_specific_lobbying_issues": query,
                    "filing_year__gte": start_year,
                    "page_size": PAGE_SIZE,
                    "ordering": "-dt_posted",
                    "page": page_num,
                }
                data = _get_page(client, params)
                for filing in data.get("results", []):
                    fid = filing.get("filing_uuid", "")
                    if not fid or fid in seen:
                        continue
                    seen.add(fid)
                    ev = _parse_filing(filing, run_id, retrieved_at)
                    if ev:
                        yield ev
                if not data.get("next"):
                    break
                page_num += 1
                time.sleep(1.5)  # LDA rate-limits hard around page 15-16 at 0.5s
