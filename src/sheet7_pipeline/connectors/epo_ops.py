"""EPO OPS connector — fetches India-relevant patent records as IP signals.

Use EPO OPS for machine retrieval of patent bibliographic records. WIPO is
discovery-only in the PRD; production patent retrieval routes through OPS/Lens.
"""
from __future__ import annotations

import math
import os
import re
import time
from datetime import UTC, datetime
from typing import Iterator
from urllib.parse import quote_plus

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..ids import event_id as make_event_id
from ..schema import EvidenceEvent

OPS_BASE = "https://ops.epo.org/3.2/rest-services"
OPS_AUTH_URL = "https://ops.epo.org/3.2/auth/accesstoken"
MAX_RECORDS_PER_QUERY = 25

_INDIA = frozenset({"india", "indian", "bharat", "in"})
_IP = frozenset({
    "patent", "patent application", "pct", "national phase",
    "india national phase", "publication", "grant", "applicant",
    "assignee", "owner", "intellectual property", "ip filing",
})


def _as_list(value: object) -> list[object]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _local(key: str) -> str:
    return key.split(":", 1)[-1]


def _child(obj: object, name: str) -> object | None:
    if not isinstance(obj, dict):
        return None
    for key, value in obj.items():
        if _local(key) == name:
            return value
    return None


def _descendants(obj: object, name: str) -> Iterator[object]:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if _local(key) == name:
                for item in _as_list(value):
                    yield item
            yield from _descendants(value, name)
    elif isinstance(obj, list):
        for item in obj:
            yield from _descendants(item, name)


def _text(obj: object) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj.strip()
    if isinstance(obj, (int, float)):
        return str(obj)
    if isinstance(obj, dict):
        for key in ("$", "#text", "value"):
            if key in obj:
                return _text(obj[key])
        return " ".join(part for part in (_text(v) for v in obj.values()) if part)
    if isinstance(obj, list):
        return " ".join(part for part in (_text(v) for v in obj) if part)
    return ""


def _doc_id(doc: object) -> dict[str, str]:
    return {
        "type": str(doc.get("@document-id-type", "")) if isinstance(doc, dict) else "",
        "country": _text(_child(doc, "country")),
        "number": _text(_child(doc, "doc-number")),
        "kind": _text(_child(doc, "kind")),
        "date": _text(_child(doc, "date")),
    }


def _best_doc_id(parent: object, preferred: str = "docdb") -> dict[str, str]:
    ids = [_doc_id(d) for d in _as_list(_child(parent, "document-id"))]
    return (
        next((d for d in ids if d["type"] == preferred and d["country"] and d["number"]), None)
        or next((d for d in ids if d["country"] and d["number"]), None)
        or {"type": "", "country": "", "number": "", "kind": "", "date": ""}
    )


def _docdb_ref(ref: dict[str, str]) -> str:
    parts = [ref["country"], ref["number"]]
    if ref.get("kind"):
        parts.append(ref["kind"])
    return ".".join(p for p in parts if p)


def _publication_refs(data: dict) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for pub in _descendants(data, "publication-reference"):
        ref = _best_doc_id(pub)
        if ref["country"] and ref["number"]:
            refs.append(ref)
    return refs


def _exchange_documents(data: dict) -> list[dict]:
    docs: list[dict] = []
    for doc in _descendants(data, "exchange-document"):
        if isinstance(doc, dict):
            docs.append(doc)
    return docs


def _first_date(*values: str) -> datetime | None:
    for value in values:
        if not value:
            continue
        try:
            return datetime.strptime(value[:8], "%Y%m%d").replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _country_system(jurisdictions: set[str]) -> str:
    if "IN" in jurisdictions:
        return "IN"
    if "WO" in jurisdictions:
        return "WO"
    if "EP" in jurisdictions:
        return "EU"
    return sorted(jurisdictions)[0] if jurisdictions else "OTHER"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:80] or "unknown"


_APPLICANT_CC = re.compile(r"\s*\[([A-Z]{2})\]\s*$")


def _split_applicant(name: str) -> tuple[str, str]:
    """Parse trailing '[CC]' country code from an EPO applicant name.

    'ICAR-INDIAN INSTITUTE [IN]' -> ('ICAR-INDIAN INSTITUTE', 'IN').
    """
    m = _APPLICANT_CC.search(name)
    if m:
        return name[: m.start()].strip(), m.group(1)
    return name.strip(), ""


def _matched(text: str, jurisdictions: set[str]) -> set[str]:
    low = text.lower()
    matched = {t for t in _IP if t in low}
    if "IN" in jurisdictions or any(t in low for t in _INDIA - {"in"}):
        matched.add("india")
    return matched


def _candidate_score(filing_date: datetime | None, matched: set[str], jurisdictions: set[str]) -> int:
    source_rel = 10  # IP < filings/lobbying in Build Spec §5.1
    company_res = 8
    india_rel = 25 if "IN" in jurisdictions else 10 if "india" in matched else 0
    ip_signal = min(20, len(matched & _IP) * 4)
    age_days = (datetime.now(UTC).date() - filing_date.date()).days if filing_date else 730
    recency = max(0, 10 - age_days // 180)
    national_phase = 10 if "IN" in jurisdictions and "WO" in jurisdictions else 0
    return min(100, source_rel + company_res + india_rel + ip_signal + recency + national_phase)


def _parse_biblio_document(
    doc: dict, run_id: str, retrieved_at: datetime, *, foreign_only: bool = False
) -> EvidenceEvent | None:
    biblio = _child(doc, "bibliographic-data") or doc
    publication = _best_doc_id(_child(biblio, "publication-reference") or doc)
    application = _best_doc_id(_child(biblio, "application-reference") or {})
    pub_ref = _docdb_ref(publication)
    if not pub_ref:
        return None

    titles = [_text(t) for t in _as_list(_child(biblio, "invention-title")) if _text(t)]
    title = next((t for t in titles if t), "")
    abstracts = [_text(a) for a in _descendants(doc, "abstract")]
    abstract = next((a for a in abstracts if a), "")

    applicants_raw = []
    for applicant in _descendants(_child(biblio, "parties"), "applicant"):
        name = _text(_child(_child(applicant, "applicant-name"), "name"))
        if name:
            applicants_raw.append(name)
    applicants_raw = list(dict.fromkeys(applicants_raw))
    parsed = [_split_applicant(n) for n in applicants_raw]
    applicants = list(dict.fromkeys(p[0] for p in parsed if p[0]))
    applicant_countries = {p[1] for p in parsed if p[1]}
    company_name = applicants[0] if applicants else "Unknown applicant"

    # foreign-entrant filter: skip patents where every named applicant is Indian
    # (domestic filings aren't "foreign entering India" signals). Mirrors SEC's India-HQ filter.
    if foreign_only and applicant_countries and applicant_countries == {"IN"}:
        return None

    jurisdictions = {
        c.upper()
        for c in [publication["country"], application["country"]]
        if c
    }
    jurisdictions.update(
        c.upper()
        for c in re.findall(r"\b[A-Z]{2}\b", " ".join(_text(d) for d in _descendants(doc, "document-id")))
    )

    evidence_parts = [
        f"[Title] {title}" if title else "",
        f"[Abstract] {abstract}" if abstract else "",
        f"[Applicants] {'; '.join(applicants[:5])}" if applicants else "",
        f"[Jurisdictions] {'|'.join(sorted(jurisdictions))}" if jurisdictions else "",
    ]
    evidence_text = " ".join(part for part in evidence_parts if part)
    matched = _matched(evidence_text, jurisdictions)
    if "india" not in matched and "IN" not in jurisdictions:
        return None

    filing_date = _first_date(publication["date"], application["date"])
    score = _candidate_score(filing_date, matched, jurisdictions)
    if score < 50:
        return None

    age_days = (retrieved_at.date() - filing_date.date()).days if filing_date else 365
    decay = round(math.exp(-max(0, age_days) / 365), 4)
    source_url = f"https://worldwide.espacenet.com/patent/search?q={quote_plus(pub_ref.replace('.', ''))}"

    return EvidenceEvent(
        event_id=make_event_id("epo_ops", pub_ref, company_name, filing_date.date().isoformat() if filing_date else ""),
        run_id=run_id,
        retrieved_at=retrieved_at,
        filing_date=filing_date,
        source="epo_ops",
        country_system=_country_system(jurisdictions),
        disclosure_layer="ip",
        company_name=company_name,
        entity_key=f"epo_ops:{_slug(company_name)}",
        company_ids={
            "publication_ref": pub_ref,
            "application_ref": _docdb_ref(application),
            "applicant_country": "|".join(sorted(applicant_countries)) if applicant_countries else "",
        },
        sector="other",
        document_type=f"PATENT-{publication.get('kind') or 'PUB'}",
        source_url=source_url,  # type: ignore[arg-type]
        evidence_text=evidence_text,
        sections_hit=[label for label, text in [
            ("Title", title), ("Abstract", abstract), ("Applicants", "; ".join(applicants)),
            ("Jurisdictions", "|".join(sorted(jurisdictions))),
        ] if text],
        matched_terms=sorted(matched),
        signal_label="india_ip_market_entry",
        candidate_score=score,
        candidate_label="india_ip_market_entry",
        candidate_reason=f"OPS patent bibliographic record with {pub_ref} and India-relevant jurisdiction/text",
        likely_noise=score < 45,
        decay_weight=decay,
    )


# Broad discovery queries — pn=IN means published in the Indian patent system
# (a foreign entity entering India via IP). ab= is abstract, single words only
# (EPO OPS CQL rejects quoted multi-word phrases). 404 = no results; 400 = bad
# query; both handled gracefully in fetch(). Domestic [IN] applicants are filtered
# out in _parse_biblio_document (foreign-entrant filter).
_DISCOVERY_QUERIES: list[str] = [
    'pn=IN AND ab=manufacturing',
    'pn=IN AND ab=semiconductor',
    'pn=IN AND ab=pharmaceutical',
    'pn=IN AND ab=automotive',
    'pn=IN AND ab=greenfield',
    'pn=IN AND ab=battery',
    'pn=IN AND ab=renewable',
    'pn=IN AND ab=telecommunications',
    'pn=IN AND ab=aerospace',
    'pn=IN AND ab=chemical',
]


def _build_queries(applicants: list[str]) -> list[str]:
    return [f'pa="{applicant}" and pn=IN' for applicant in applicants]


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=4, max=60))
def _access_token(client: httpx.Client, client_id: str, client_secret: str) -> str:
    response = client.post(
        OPS_AUTH_URL,
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=4, max=60))
def _get_json(client: httpx.Client, url: str, token: str, *, params: dict | None = None, headers: dict | None = None) -> dict | None:
    """Return parsed JSON, None for 404 (no results), None for 400 (bad query — don't retry).
    Retries on 429 / 5xx only."""
    request_headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    if headers:
        request_headers.update(headers)
    response = client.get(url, params=params, headers=request_headers, timeout=30)
    if response.status_code in (404, 400):
        return None  # 404 = empty result set; 400 = invalid query — both non-retriable
    if response.status_code == 429:
        time.sleep(60)
    response.raise_for_status()
    return response.json()


def fetch(
    run_id: str,
    *,
    applicants: list[str] | None = None,
    queries: list[str] | None = None,
    max_results: int = 100,
    discovery: bool = True,
    client_id: str | None = None,
    client_secret: str | None = None,
    verbose: bool = False,
) -> Iterator[EvidenceEvent]:
    """Yield EvidenceEvent rows from EPO OPS.

    Discovery mode (default): sweeps _DISCOVERY_QUERIES to surface companies
    filing PCT patents that designate India — mirrors how SEC uses EFTS.
    Targeted mode: pass applicants/queries for known-company lookups.
    Both modes can run together.
    """
    client_id = client_id or os.environ.get("EPO_OPS_CLIENT_ID")
    client_secret = client_secret or os.environ.get("EPO_OPS_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("EPO_OPS_CLIENT_ID and EPO_OPS_CLIENT_SECRET are required")

    targeted = list(queries or []) + _build_queries(applicants or [])
    discovery_qs = _DISCOVERY_QUERIES if discovery else []
    # (query, foreign_only): discovery filters out domestic Indian applicants;
    # targeted lookups return whatever the user asked for.
    search_queries = [(q, True) for q in discovery_qs] + [(q, False) for q in targeted]
    if not search_queries:
        raise ValueError("Provide at least one applicant or CQL query, or enable discovery mode")

    retrieved_at = datetime.now(UTC)
    seen_refs: set[str] = set()
    emitted = 0

    with httpx.Client(headers={"User-Agent": os.environ.get("SEC_USER_AGENT", "TAG-Sheet7/0.1")}) as client:
        token = _access_token(client, client_id, client_secret)
        for query, foreign_only in search_queries:
            if emitted >= max_results:
                break
            search = _get_json(
                client,
                f"{OPS_BASE}/published-data/search",
                token,
                params={"q": query},
                headers={"Range": f"1-{min(MAX_RECORDS_PER_QUERY, max_results)}"},
            )
            if search is None:
                if verbose:
                    print(f"[epo_ops] query={query!r} → no results or invalid query, skipping")
                continue
            refs = _publication_refs(search)
            if verbose:
                print(f"[epo_ops] query={query!r} refs={len(refs)}")
            for ref in refs:
                if emitted >= max_results:
                    break
                docdb = _docdb_ref(ref)
                if not docdb or docdb in seen_refs:
                    continue
                seen_refs.add(docdb)
                detail = _get_json(
                    client,
                    f"{OPS_BASE}/published-data/publication/docdb/{docdb}/biblio",
                    token,
                )
                if detail is None:
                    continue
                for doc in _exchange_documents(detail):
                    ev = _parse_biblio_document(doc, run_id, retrieved_at, foreign_only=foreign_only)
                    if ev:
                        emitted += 1
                        yield ev
                time.sleep(1.0)
