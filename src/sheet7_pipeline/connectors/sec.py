"""SEC EDGAR connector — fetches 10-K and 20-F filings and yields EvidenceEvent rows.

Flow:
  1. EFTS full-text search discovers CIKs of companies mentioning India/China+1.
  2. For each unique CIK, fetch the company's most recent 10-K or 20-F (not the
     EFTS-matched one, so old EFTS hits still yield fresh filings).
  3. Extract Items 1, 1A, 7 (10-K) or .business (20-F) via edgartools.
  4. Keyword prefilter; extract context windows around hits.
  5. Score (Layer A) and yield EvidenceEvent.
"""
from __future__ import annotations

import math
import os
import re
import time
from datetime import UTC, date, datetime
from typing import Iterator

import httpx
from edgar import Company, set_identity
from tenacity import retry, stop_after_attempt, wait_exponential

from ..ids import event_id as make_event_id
from ..schema import EvidenceEvent, SignalLabel

EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
PAGE_SIZE = 100
WINDOW_CHARS = 400   # context chars around each keyword hit
MAX_WINDOWS = 4      # max windows extracted per section

# EFTS queries — forward-looking phrases to surface entrant intent, not just awareness
_SEARCH_QUERIES = [
    '"India" "new facility"',
    '"India" "plan to" "manufacturing"',
    '"India" "market entry"',
    '"India" "China plus one"',
    '"India" "greenfield"',
    '"India" "capex"',
    '"India" "expand" "invest"',
    '"Bharat" "invest"',
]

# High-signal stated-intent phrases that confirm active India entry plans
_INTENT_PHRASES = frozenset({
    "new facility in india",
    "manufacturing in india",
    "expand in india",
    "india market entry",
    "india capex",
    "entering india",
    "launch in india",
    "india expansion",
    "invest in india",
    "production in india",
})

# Keyword sets (from Build Spec §3) — same sets as LDA connector
_INDIA = frozenset({"india", "indian", "bharat", "south asia", "indo-pacific"})
_CHINA1 = frozenset({
    "china+1", "china plus one", "supply chain diversification",
    "supply-chain resilience", "derisking", "de-risking", "friendshoring",
    "nearshoring", "reshoring", "relocation", "manufacturing shift",
    "production transfer", "supplier concentration", "alternative geographies",
    "non-china sourcing",
})
_ACTION = frozenset({
    "invest", "investment", "capex", "expand", "expansion", "new facility",
    "plant", "factory", "manufacturing", "production base", "subsidiary",
    "branch", "office", "regional hub", "acquisition", "joint venture",
    "mou", "restructuring", "evaluating", "planning", "entering", "launching",
})
_POLICY = frozenset({
    "tariff", "customs", "market access", "trade", "export controls",
    "sanctions", "fdi", "data localization", "telecom", "pharma",
    "medical devices", "defence", "defense", "semiconductors",
    "energy", "infrastructure", "tax treaty",
})
_ALL = _INDIA | _CHINA1 | _ACTION | _POLICY

_COUNTRY_MAP = {"US": "US", "GB": "UK", "JP": "JP", "DE": "EU", "FR": "EU",
                "IN": "IN", "CA": "CA", "AU": "AU", "KR": "KR", "CN": "CN"}

# SEC SIC codes → rough sector mapping (top-level only)
_SIC_SECTOR = {
    "28": "pharma", "29": "energy", "36": "tech", "37": "auto",
    "38": "tech", "48": "telecom", "49": "energy", "73": "tech",
    "87": "consulting",
}


def _matched(text: str) -> set[str]:
    low = text.lower()
    return {t for t in _ALL if t in low}


def _signal_label(matched: set[str]) -> SignalLabel:
    if matched & _CHINA1:
        return "china_plus_one"
    if matched & _ACTION and matched & _INDIA:
        return "india_investment"
    if matched & _POLICY:
        return "india_policy_lobbying"
    return "india_interest"


def _recency_score(filing_date: date) -> int:
    age_days = (datetime.now(UTC).date() - filing_date).days
    if age_days <= 90: return 10
    if age_days <= 180: return 8
    if age_days <= 365: return 6
    if age_days <= 730: return 3
    return 1


def _candidate_score(
    matched: set[str],
    filing_date: date,
    sections_hit: list[str],
    source_reliability: int = 25,
    india_count: int = 0,
    intent_boost: int = 0,
) -> int:
    company_res = 15
    india_rel = min(20, len(matched & (_INDIA | _CHINA1)) * 5)
    action = min(25, len(matched & _ACTION) * 4 + len(matched & _POLICY) * 2)
    recency = _recency_score(filing_date)
    multi_section = 3 if len(sections_hit) > 1 else 0
    local_signal = min(5, 2 + multi_section)
    density = min(10, india_count // 5)  # ponytail: +2/5 mentions, cap 10
    return min(100, source_reliability + company_res + india_rel + action + recency + local_signal + density + intent_boost)


def _extract_windows(text: str, matched_terms: set[str]) -> list[str]:
    """Extract up to MAX_WINDOWS context windows, India/China+1 terms get first slots."""
    low = text.lower()
    windows: list[str] = []
    seen_buckets: set[int] = set()

    def _scan(terms: set[str], limit: int) -> None:
        for term in sorted(terms, key=len, reverse=True):
            pos = 0
            while len(windows) < limit:
                idx = low.find(term, pos)
                if idx == -1:
                    break
                bucket = idx // WINDOW_CHARS
                if bucket not in seen_buckets:
                    seen_buckets.add(bucket)
                    start = max(0, idx - WINDOW_CHARS // 2)
                    end = min(len(text), idx + len(term) + WINDOW_CHARS // 2)
                    windows.append(text[start:end].strip())
                pos = idx + 1

    # India/China+1 terms anchor the first windows — always present if they hit
    _scan(matched_terms & (_INDIA | _CHINA1), MAX_WINDOWS - 1)
    # Fill remaining slots with action/policy context
    _scan(matched_terms & (_ACTION | _POLICY), MAX_WINDOWS)
    return windows


def _extract_sections(doc: object, form: str) -> dict[str, str]:
    """Return {section_label: text} for the strategic sections of a filing."""
    sections: dict[str, str] = {}

    # Business description — present on both TenK and TwentyF
    try:
        biz = str(doc.business or "")  # type: ignore[attr-defined]
        if biz.strip():
            sections["Business"] = biz
    except Exception:
        pass

    if form == "10-K":
        for part, item, label in [("I", "1A", "Item 1A"), ("II", "7", "Item 7")]:
            try:
                text = str(doc.get_item_with_part(part=part, item=item) or "")  # type: ignore[attr-defined]
                if text.strip():
                    sections[label] = text
            except Exception:
                pass

    return sections


def _efts_page(client: httpx.Client, params: dict) -> dict | None:
    """Fetch one EFTS page. Returns None on 500 (EFTS flakiness at high offsets)."""
    for attempt in range(3):
        try:
            r = client.get(EFTS_URL, params=params, timeout=30)
            if r.status_code == 500:
                return None  # ponytail: EFTS 500s on page 2+ are a known server bug; skip
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError:
            raise
        except Exception:
            if attempt == 2:
                return None
            time.sleep(2 ** attempt)
    return None


def _discover_ciks(queries: list[str], max_pages: int, headers: dict) -> set[str]:
    """Return unique CIKs from EFTS full-text search across all queries."""
    ciks: set[str] = set()
    with httpx.Client(headers=headers) as client:
        for query in queries:
            for page in range(max_pages):
                params = {
                    "q": query,
                    "forms": "10-K,20-F",
                    "from": page * PAGE_SIZE,
                    "size": PAGE_SIZE,
                }
                data = _efts_page(client, params)
                if data is None:
                    break  # 500 or error — skip remaining pages for this query
                hits = data.get("hits", {}).get("hits", [])
                if not hits:
                    break
                for h in hits:
                    for cik in h.get("_source", {}).get("ciks", []):
                        ciks.add(cik.lstrip("0"))
                time.sleep(0.2)
    return ciks


def _country_from_submissions(cik: str, headers: dict) -> str:
    """Fetch country code from EDGAR submissions JSON for foreign filers."""
    try:
        r = httpx.get(
            SUBMISSIONS_URL.format(cik=cik.zfill(10)),
            headers=headers, timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        country = (
            data.get("addresses", {}).get("business", {}).get("stateOrCountry")
            or data.get("stateOfIncorporation")
            or ""
        )
        return _COUNTRY_MAP.get(country, country or "OTHER")
    except Exception:
        return "OTHER"


def fetch(
    run_id: str,
    *,
    start_date: str = "2024-01-01",
    max_efts_pages: int = 2,
    queries: list[str] | None = None,
    verbose: bool = False,
) -> Iterator[EvidenceEvent]:
    """Yield EvidenceEvent rows for recent 10-K/20-F filings with India/China+1 intent.

    max_efts_pages: pages of EFTS results per query (100 results/page).
    start_date: skip filings older than this date (ISO format).
    """
    ua = os.environ.get("SEC_USER_AGENT", "TAG-Sheet7/0.1")
    set_identity(ua)
    headers = {"User-Agent": ua}
    cutoff = date.fromisoformat(start_date)
    retrieved_at = datetime.now(UTC)
    search_queries = queries or _SEARCH_QUERIES

    # Step 1: discover CIKs via EFTS
    ciks = _discover_ciks(search_queries, max_efts_pages, headers)
    if verbose:
        print(f"[sec] discovered {len(ciks)} unique CIKs from EFTS")

    # Step 2: for each CIK, fetch most recent annual filing
    processed = 0
    for cik in sorted(ciks):
        try:
            company = Company(cik)
            filings = company.get_filings(form=["10-K", "20-F"])
            if not filings or len(filings) == 0:
                continue
            filing = filings.get_filing_at(0)
            if filing.filing_date < cutoff:
                continue  # most recent filing is too old

            form = filing.form
            doc = filing.obj()
            sections = _extract_sections(doc, form)
            if not sections:
                continue

            # Step 3: keyword prefilter across all sections
            all_text = " ".join(sections.values())
            matched = _matched(all_text)
            if not matched or not (matched & _INDIA):
                continue

            # Step 4: extract context windows per section, stitch evidence_text
            stitched_parts: list[str] = []
            sections_hit: list[str] = []
            all_matched: set[str] = set()
            for section_label, text in sections.items():
                sec_matched = _matched(text)
                if not sec_matched:
                    continue
                windows = _extract_windows(text, sec_matched & _ALL)
                if windows:
                    sections_hit.append(section_label)
                    all_matched |= sec_matched
                    for w in windows:
                        stitched_parts.append(f"[{section_label}] {w}")

            if not stitched_parts:
                continue

            evidence_text = " ".join(stitched_parts)
            cik_padded = str(cik).zfill(10)
            filing_year = filing.filing_date.year
            form_type = form.replace("-", "").lower()

            country_system = "US" if form == "10-K" else _country_from_submissions(cik_padded, headers)

            # Filter 3: skip India-HQ companies (Infosys, Wipro etc. — not foreign entrants)
            if country_system == "IN":
                if verbose:
                    print(f"[sec] skip CIK={cik} India-HQ")
                continue

            # Filter 4: 20-F non-India = foreign company with SEC filings → strong signal, boost reliability
            source_reliability = 25 if form == "10-K" else 30

            india_count = sum(all_text.lower().count(t) for t in _INDIA)
            intent_boost = 15 if any(p in all_text.lower() for p in _INTENT_PHRASES) else 0
            score = _candidate_score(
                all_matched, filing.filing_date, sections_hit,
                source_reliability, india_count, intent_boost,
            )
            if score < 50:
                continue

            age_days = (retrieved_at.date() - filing.filing_date).days
            decay = round(math.exp(-max(0, age_days) / 180), 4)
            signal_label = _signal_label(all_matched)

            # Ticker from Company if available
            ticker = getattr(company, "tickers", None)
            ticker_str = ticker[0] if ticker and len(ticker) > 0 else ""

            eid = make_event_id("sec", cik_padded, form_type, str(filing_year))

            yield EvidenceEvent(
                event_id=eid,
                run_id=run_id,
                retrieved_at=retrieved_at,
                filing_date=datetime.combine(filing.filing_date, datetime.min.time(), tzinfo=UTC),
                source="sec",
                country_system=country_system,
                disclosure_layer="filing",
                company_name=company.name or "Unknown",
                entity_key=f"sec:{cik_padded}",
                company_ids={"cik": cik_padded, "ticker": ticker_str},
                sector="other",
                document_type=form,
                source_url=filing.filing_url or f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik_padded}",  # type: ignore[arg-type]
                evidence_text=evidence_text,
                sections_hit=sections_hit,
                matched_terms=sorted(all_matched),
                signal_label=signal_label,
                candidate_score=score,
                candidate_label=signal_label,
                candidate_reason=f"{len(all_matched)} matched terms across {len(sections_hit)} sections" + ("; intent_boost+15" if intent_boost else ""),
                likely_noise=score < 35,
                decay_weight=decay,
            )

            processed += 1
            if verbose:
                print(f"[sec] [{score:3d}] {company.name[:45]:<45} {form} {filing.filing_date}")

            time.sleep(0.3)  # polite crawl; SEC asks for ≤10 req/s

        except Exception as exc:
            if verbose:
                print(f"[sec] skip CIK={cik}: {exc}")
            continue
