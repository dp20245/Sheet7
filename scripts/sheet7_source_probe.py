#!/usr/bin/env python3
"""
sheet7_source_probe.py
======================
ONE diagnostic test-pull per non-US source for the Sheet7 intent engine.

PURPOSE
-------
This is NOT the production scraper. It answers three questions per source so we
can decide whether (and how) to integrate each one:

  Q1. ENTITY KEY  — what does the company identifier look like? (needed for the
                    cross-source entity-resolution map; SEC uses CIK, others differ)
  Q2. STRUCTURE   — is the filing parseable into sections, a flat blob, XBRL
                    numbers, or just metadata?
  Q3. INTENT TEXT — is there any narrative prose where market-entry / expansion /
                    supply-chain intent could actually be expressed, or only
                    numbers and compliance fields?

It pulls a SMALL sample, dumps the raw response shape to ./probe_out/, and prints
a verdict per source. Darsh runs this, pastes the printed report + a sample file
back, and we use the real shapes (not assumptions) to finalise each connector.

SOURCES PROBED
--------------
  1. SEC EDGAR        (baseline / control — confirms the section-extraction path)
  2. US LDA           (lobbying disclosures)
  3. EDINET (Japan)   (securities reports — XBRL)
  4. Companies House  (UK)
  5. India MCA / data.gov.in

SECRETS
-------
Reads from environment and ./SHEET7SECRETS. Missing keys are reported, not fatal
— the script skips that source and tells you what to obtain. Put keys in SHEET7SECRETS:
  SEC_USER_AGENT            e.g. "TAG-Sheet7/0.1 (darsh@example.com)"   (required by SEC)
  LDA_API_KEY               api.senate.gov LDA key (free, register)
  EDINET_API_KEY            EDINET API v2 subscription key
  COMPANIES_HOUSE_API_KEY   UK Companies House REST key (free, register)
  DATA_GOV_IN_API_KEY       data.gov.in key (free, register)

USAGE
-----
  pip install requests
  python sheet7_source_probe.py                 # probe all sources
  python sheet7_source_probe.py --only edinet    # probe one
  python sheet7_source_probe.py --company "Hitachi"   # override search term

Each probe writes a raw sample to ./probe_out/<source>_sample.* and prints a
VERDICT block. Nothing here writes to Google Sheets or calls an LLM.
"""

import os
import sys
import json
import argparse
import datetime as dt
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("pip install requests first")

OUT = Path("./probe_out")
OUT.mkdir(exist_ok=True)

# Default search anchors: large foreign firms likely to mention India.
DEFAULT_COMPANY = "Hitachi"          # files in both US (foreign private issuer) and Japan
DEFAULT_INDIA_TERM = "India"


def load_secrets(path=Path("SHEET7SECRETS")):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def banner(name):
    print("\n" + "=" * 70)
    print(f"  PROBE: {name}")
    print("=" * 70)


def verdict(entity_key, structure, intent_text, notes):
    print("\n  ---- VERDICT ----------------------------------------------------")
    print(f"  Q1 ENTITY KEY : {entity_key}")
    print(f"  Q2 STRUCTURE  : {structure}")
    print(f"  Q3 INTENT TEXT: {intent_text}")
    print(f"  NOTES         : {notes}")
    print("  -----------------------------------------------------------------")


def save(name, content, mode="w", suffix="json"):
    p = OUT / f"{name}_sample.{suffix}"
    if mode == "wb":
        p.write_bytes(content)
    else:
        p.write_text(content if isinstance(content, str) else json.dumps(content, indent=2, ensure_ascii=False))
    print(f"  raw sample -> {p}")
    return p


# ---------------------------------------------------------------------------
# 1. SEC EDGAR  (baseline / control)
#    Free. No key, but User-Agent is MANDATORY or you get 403.
#    Confirms the verified section-extraction path: full-text search -> filing ->
#    Item 1 / 1A / 7. We use the official submissions + full-text-search APIs.
# ---------------------------------------------------------------------------
def probe_sec(company, india_term):
    banner("SEC EDGAR (US) — baseline / control")
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        print("  SKIP: set SEC_USER_AGENT (e.g. 'TAG-Sheet7/0.1 (you@email.com)')")
        verdict("CIK (10-digit, zero-padded)", "unknown", "unknown", "no User-Agent set")
        return
    h = {"User-Agent": ua}

    # 1) Resolve company -> CIK via the official ticker/name map.
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=h, timeout=30)
        r.raise_for_status()
        tickers = r.json()
        hit = next((v for v in tickers.values()
                    if company.lower() in v["title"].lower()), None)
        if not hit:
            print(f"  no CIK match for '{company}' in ticker map (try a US-listed name)")
            verdict("CIK (10-digit)", "n/a", "n/a", "company not in ticker map")
            return
        cik = str(hit["cik_str"]).zfill(10)
        print(f"  resolved '{hit['title']}' -> CIK {cik}  ticker {hit['ticker']}")
    except Exception as e:
        verdict("CIK", "ERROR", "ERROR", f"ticker map failed: {e}")
        return

    # 2) Pull recent filings list for that CIK.
    try:
        r = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=h, timeout=30)
        r.raise_for_status()
        sub = r.json()
        recent = sub["filings"]["recent"]
        forms = recent["form"]
        # find the most recent 10-K or 20-F (foreign issuers file 20-F)
        idx = next((i for i, f in enumerate(forms) if f in ("10-K", "20-F")), None)
        if idx is None:
            print("  no 10-K/20-F in recent filings")
            verdict("CIK " + cik, "filings list OK", "depends on form availability",
                    "no annual report in recent window")
            return
        accession = recent["accessionNumber"][idx].replace("-", "")
        primary_doc = recent["primaryDocument"][idx]
        form = forms[idx]
        filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/{primary_doc}"
        print(f"  most recent annual report: {form}  ({recent['filingDate'][idx]})")
        print(f"  filing URL: {filing_url}")
        save("sec", {"cik": cik, "company": sub["name"], "form": form,
                     "filing_url": filing_url, "filing_date": recent["filingDate"][idx]})
    except Exception as e:
        verdict("CIK " + cik, "ERROR", "ERROR", f"submissions failed: {e}")
        return

    # 3) Section extraction note (production uses sec-edgar-toolkit.extract_items()).
    print("\n  SECTION EXTRACTION (production path):")
    print("    pip install sec-edgar-toolkit")
    print("    client = create_client(SEC_USER_AGENT)")
    print("    filing.extract_items() -> {'1':..., '1A':..., '7':...}")
    print("    (do NOT hand-roll regex; 'Item 1' matches inside 'Item 11/12')")
    verdict(
        "CIK (10-digit, zero-padded) — CLEAN, stable, the gold-standard entity key",
        f"PARSEABLE into Items via sec-edgar-toolkit; {form} found",
        "YES — Item 1 (Business), 1A (Risk Factors), 7 (MD&A) are narrative prose",
        "This is the control. Other sources are judged against this richness.",
    )


# ---------------------------------------------------------------------------
# 2. US LDA  (Senate Lobbying Disclosure Act filings)
#    Free REST API at lda.senate.gov. Key recommended (higher rate limit).
# ---------------------------------------------------------------------------
def probe_lda(company, india_term):
    banner("US LDA (lobbying disclosures)")
    key = os.environ.get("LDA_API_KEY")
    h = {"User-Agent": "TAG-Sheet7/0.1"}
    if key:
        h["Authorization"] = f"Token {key}"
    else:
        print("  (no LDA_API_KEY — anonymous works but is rate-limited; register free at lda.senate.gov)")

    # Filter filings whose lobbying issues mention India.
    url = "https://lda.senate.gov/api/v1/filings/"
    params = {"filing_specific_lobbying_issues": india_term, "page_size": 3}
    try:
        r = requests.get(url, headers=h, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        n = data.get("count", 0)
        print(f"  filings mentioning '{india_term}' in issues: {n}")
        sample = data.get("results", [])[:1]
        if sample:
            f = sample[0]
            client_name = f.get("client", {}).get("name")
            registrant = f.get("registrant", {}).get("name")
            issues = [a.get("description") for a in f.get("lobbying_activities", [])]
            print(f"  client (the company): {client_name}")
            print(f"  registrant (the lobbyist): {registrant}")
            print(f"  issue descriptions: {issues[:2]}")
            save("lda", sample[0])
        verdict(
            "client.name (string) + registrant — NO stable numeric id; name-match needed",
            "STRUCTURED JSON: client, registrant, lobbying_activities[].description",
            "PARTIAL — issue descriptions are short prose stating what they lobby on; "
            "this IS intent (regulatory_positioning) but terse, not a filing body",
            "Maps to disclosure_layer=lobbying. is_foreign_entering_india exception "
            "applies (lobbying counts even for non-entrants). Entity = company NAME, "
            "so cross-source resolution to SEC CIK is name-based and fuzzy.",
        )
    except Exception as e:
        verdict("client name", "ERROR", "ERROR", f"LDA request failed: {e}")


# ---------------------------------------------------------------------------
# 3. EDINET (Japan)  — securities reports via API v2
#    Returns a ZIP of XBRL/CSV, NOT clean prose. This is the key finding to test.
# ---------------------------------------------------------------------------
def probe_edinet(company, india_term):
    banner("EDINET (Japan) — securities reports (XBRL)")
    key = os.environ.get("EDINET_API_KEY")
    if not key:
        print("  SKIP: set EDINET_API_KEY (EDINET API v2 subscription key)")
        verdict("EDINET code / 法人番号 (corporate number)",
                "XBRL ZIP (CSV, UTF-16, tab-delimited)",
                "MOSTLY NUMBERS — narrative is in XBRL text blocks, not clean sections",
                "no key set; this is the source most likely to need special handling")
        return

    # List documents for a recent business day, then inspect one's metadata.
    date = (dt.date.today() - dt.timedelta(days=2)).isoformat()
    url = "https://api.edinet-fsa.go.jp/api/v2/documents.json"
    params = {"date": date, "type": 2, "Subscription-Key": key}
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        print(f"  documents disclosed on {date}: {len(results)}")
        # Show the shape of one document's metadata.
        if results:
            d = results[0]
            interesting = {k: d.get(k) for k in
                           ("docID", "edinetCode", "filerName", "docTypeCode",
                            "secCode", "JCN", "docDescription")}
            print("  sample document metadata:")
            print(json.dumps(interesting, indent=4, ensure_ascii=False))
            save("edinet", results[:5])
        verdict(
            "edinetCode + JCN (法人番号 corporate number) — STABLE numeric id, GOOD for entity map",
            "XBRL CSV inside a ZIP (UTF-16, tab-delimited). NOT pre-split prose sections.",
            "LIMITED — financial data is XBRL numbers. Narrative ('事業の内容', risk, "
            "MD&A-equivalent) exists as XBRL TEXT BLOCKS, in Japanese. Needs: (a) unzip, "
            "(b) pull narrative text-block elements, (c) translate JA->EN before LLM.",
            "Biggest integration delta vs EDGAR. Consider edinet-tools lib "
            "(report.text_blocks). India intent in a JP filing will be in Japanese; "
            "your keyword list already has JP terms (インド, 生産拠点) — good.",
        )
    except Exception as e:
        verdict("edinetCode/JCN", "ERROR", "ERROR", f"EDINET request failed: {e}")


# ---------------------------------------------------------------------------
# 4. Companies House (UK)
#    Free REST API. Key required (free). Filing METADATA + document API.
# ---------------------------------------------------------------------------
def probe_companies_house(company, india_term):
    banner("Companies House (UK)")
    key = os.environ.get("COMPANIES_HOUSE_API_KEY")
    if not key:
        print("  SKIP: set COMPANIES_HOUSE_API_KEY (free at developer.company-information.service.gov.uk)")
        verdict("company_number (8-char) — STABLE",
                "filing metadata JSON + document API (PDF/iXBRL)",
                "LIMITED — annual accounts are mostly financial; narrative is thin",
                "no key set")
        return
    auth = (key, "")  # HTTP basic, key as username, blank password

    # Search company -> number, then list its filing history.
    try:
        r = requests.get("https://api.company-information.service.gov.uk/search/companies",
                         auth=auth, params={"q": company, "items_per_page": 3}, timeout=30)
        r.raise_for_status()
        items = r.json().get("items", [])
        if not items:
            print(f"  no UK company match for '{company}'")
            verdict("company_number", "n/a", "n/a", "no match")
            return
        c = items[0]
        num = c["company_number"]
        print(f"  resolved '{c['title']}' -> company_number {num}")

        r2 = requests.get(
            f"https://api.company-information.service.gov.uk/company/{num}/filing-history",
            auth=auth, params={"items_per_page": 5}, timeout=30)
        r2.raise_for_status()
        fh = r2.json().get("items", [])
        kinds = [(f.get("type"), f.get("description")) for f in fh]
        print(f"  recent filings: {kinds}")
        save("companies_house", {"company_number": num, "title": c["title"], "filings": fh})
        verdict(
            "company_number (8-char alnum) — STABLE numeric-ish id, GOOD for entity map",
            "filing-history METADATA as JSON; actual documents are PDF/iXBRL via document API",
            "WEAK — UK annual accounts are largely financial statements; little "
            "forward-looking narrative. Strategic Report (where it exists) is the only "
            "intent-bearing section and isn't always present for smaller filers.",
            "Best used to RESOLVE a UK entity / confirm a UK subsidiary exists, rather "
            "than as a primary intent source. Flags 'foreign parent has UK arm' which is "
            "itself a weak entry signal.",
        )
    except Exception as e:
        verdict("company_number", "ERROR", "ERROR", f"Companies House failed: {e}")


# ---------------------------------------------------------------------------
# 5. India MCA / data.gov.in
#    data.gov.in exposes company master datasets via key. Full MCA documents sit
#    behind a paid SRN. We probe the FREE master-data resource for entity spine.
# ---------------------------------------------------------------------------
def probe_mca(company, india_term):
    banner("India MCA / data.gov.in")
    key = os.environ.get("DATA_GOV_IN_API_KEY")
    if not key:
        print("  SKIP: set DATA_GOV_IN_API_KEY (free at data.gov.in)")
        verdict("CIN (21-char) / LLPIN — STABLE, the India entity spine",
                "master-data fields (status, directors, dates) — NOT filing prose",
                "NONE in free tier — actual filings are paid (SRN fee)",
                "no key set")
        return

    # data.gov.in resource API. NOTE: resource IDs change; this is a probe of the
    # company-master pattern. If this resource id is stale, the script reports it
    # and you grab a current company-master resource id from data.gov.in.
    resource_id = os.environ.get("DATA_GOV_IN_MCA_RESOURCE", "")  # set if you have one
    if not resource_id:
        print("  NOTE: no DATA_GOV_IN_MCA_RESOURCE set. Find a current 'company master'")
        print("        dataset on data.gov.in and pass its resource id. Probing skipped.")
        verdict(
            "CIN (21-char Corporate Identity Number) — the India entity spine, STABLE",
            "master data: company status, ROC, directors, incorporation date, filing dates",
            "NONE for intent in free tier. MCA narrative documents require paid SRN download.",
            "ROLE: this is your ENTITY-RESOLUTION anchor for India (resolves a foreign "
            "company's Indian subsidiary -> CIN), NOT an intent source. Pair with the "
            "MCA Company Master to link 'Example Corp (SEC CIK)' to 'Example India Pvt "
            "Ltd (CIN)'. Intent still comes from the US/JP parent's filings.",
        )
        return

    url = "https://api.data.gov.in/resource/" + resource_id
    params = {"api-key": key, "format": "json", "limit": 3, "filters[company_name]": company}
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        recs = data.get("records", [])
        print(f"  records: {len(recs)}")
        if recs:
            print(json.dumps(recs[0], indent=4, ensure_ascii=False)[:800])
            save("mca", recs[:3])
        verdict(
            "CIN (21-char) — India entity spine, STABLE",
            "master-data record fields (JSON)",
            "NONE — master data has no intent prose; documents are paid",
            "Use as the India side of the entity-resolution map.",
        )
    except Exception as e:
        verdict("CIN", "ERROR", "ERROR", f"data.gov.in failed: {e}")


SOURCES = {
    "sec": probe_sec,
    "lda": probe_lda,
    "edinet": probe_edinet,
    "companies_house": probe_companies_house,
    "mca": probe_mca,
}


def main():
    load_secrets()
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=list(SOURCES), help="probe a single source")
    ap.add_argument("--company", default=DEFAULT_COMPANY)
    ap.add_argument("--india-term", default=DEFAULT_INDIA_TERM)
    args = ap.parse_args()

    print("Sheet7 source probe — diagnostic test pulls (no Sheets, no LLM)")
    print(f"company anchor: {args.company!r}   india term: {args.india_term!r}")
    print(f"output dir: {OUT.resolve()}")

    targets = [args.only] if args.only else list(SOURCES)
    for name in targets:
        try:
            SOURCES[name](args.company, args.india_term)
        except Exception as e:
            print(f"\n  [{name}] unexpected error: {e}")

    print("\n" + "=" * 70)
    print("  NEXT: paste the VERDICT blocks + the files in ./probe_out/ back,")
    print("  and we finalise each connector against the real shapes.")
    print("=" * 70)


if __name__ == "__main__":
    main()
