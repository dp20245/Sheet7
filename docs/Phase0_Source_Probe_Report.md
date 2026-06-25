# Phase 0 Source Probe Report

Run date: 2026-06-20

Probe command:

```bash
python scripts/sheet7_source_probe.py
```

Raw samples are saved locally in `probe_out/`, which is git-ignored.

## Verdicts

### SEC EDGAR

- Status: works.
- Sample file: `probe_out/sec_sample.json`.
- Entity key: CIK, stable and clean. Use `entity_key=sec:<cik>`.
- Structure: annual report found as `20-F`; production path should use `sec-edgar-toolkit` section extraction.
- Intent text: yes. Business, Risk Factors, and MD&A-style sections contain narrative prose.
- Build implication: SEC remains the control source and first real connector.

Probe sample:

```text
Company: HITACHI LTD
CIK: 0000047710
Ticker: HTHIY
Form: 20-F
Filing date: 2011-06-24
URL: https://www.sec.gov/Archives/edgar/data/47710/000119312511172867/d20f.htm
```

Note: the Hitachi SEC sample is old. For production tests, use a company with recent 10-K or 20-F filings.

### US LDA

- Status: works.
- Sample file: `probe_out/lda_sample.json`.
- Entity key: no stable numeric company id; use client name and resolve later.
- Structure: structured JSON with client, registrant, and lobbying issue descriptions.
- Intent text: partial but real. Issue descriptions are short, but they can express regulatory-positioning intent.
- Build implication: LDA is a primary intent source for `regulatory_positioning`, but entity resolution is name-based.

Probe sample:

```text
India issue count: 4248
Client: SERVO CORPORATION OF AMERICA
Registrant: JEFFERSON BUSINESS CONSULTING, LLC
Issue: Export to India
```

### EDINET

- Status: works.
- Sample file: `probe_out/edinet_sample.json`.
- Entity key: `edinetCode` plus JCN; stable and useful for Japan entity mapping.
- Structure: XBRL CSV inside ZIP, UTF-16/tab-delimited. Not clean prose sections.
- Intent text: limited but possible. Narrative lives in Japanese XBRL text blocks.
- Build implication: EDINET should not be treated like EDGAR. Use `edinet-tools`/text blocks, Japanese keyword scan, and possibly translation before Layer B.

Probe sample:

```text
Documents on 2026-06-18: 720
docID: S100YCMX
edinetCode: E30982
filerName: 今村証券株式会社
docTypeCode: 120
secCode: 71750
JCN: 9220001001223
Description: 有価証券報告書－第87期(2025/04/01－2026/03/31)
```

### Companies House

- Status: failed auth.
- Sample file: none.
- Error: `401 Unauthorized`.
- Entity key if working: `company_number`, stable.
- Structure if working: company search and filing-history metadata; documents via document API.
- Intent text expectation: weak. Useful mostly as UK entity spine and occasional filing-text scan.
- Build implication: current `COMPANIES_HOUSE_API_KEY` is invalid, expired, or not accepted in Basic Auth. Fix key before building this connector.

### India MCA / data.gov.in

- Status: skipped.
- Sample file: none.
- Reason: `DATA_GOV_IN_MCA_RESOURCE` missing.
- Entity key: CIN, stable India entity spine.
- Structure expectation: master-data JSON, not filing prose.
- Intent text expectation: none in free tier. MCA documents require paid SRN download.
- Build implication: MCA is entity-resolution support, not an intent source. Need current data.gov.in Company Master resource id before probing.

## Build Consequences

- Build SEC first. It is the richest and cleanest source.
- Build LDA second. It works and gives regulatory-positioning intent, but needs name-based entity resolution.
- Keep EDINET as a secondary/high-effort source. It works, but narrative extraction is materially harder than EDGAR.
- Do not build Companies House until the key is fixed.
- Do not build MCA until `DATA_GOV_IN_MCA_RESOURCE` is supplied.
- Preserve `entity_key` as source-native: `sec:<cik>`, `edinet:<edinetCode>`, `companies_house:<company_number>`, `mca:<cin>`.

## Open Fixes

- Replace or validate `COMPANIES_HOUSE_API_KEY`.
- Find and set `DATA_GOV_IN_MCA_RESOURCE`.
- Use a fresher SEC test company than Hitachi for the first EDGAR connector test.
