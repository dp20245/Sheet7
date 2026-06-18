# TAG BD Project - Sheet 7 Public Disclosures PRD

Verified: 2026-06-17
Owner: TAG BD workflow
Build target: Claude Code / Codex engineering implementation

## 1. Product Goal

Sheet 7 tracks public-disclosure signals that indicate a non-Indian company may be relevant for TAG business development because it is:

1. Expanding into India.
2. Considering India as part of a China+1, supply-chain diversification, manufacturing relocation, market-entry, or regional HQ strategy.
3. Lobbying on India, South Asia, trade, tariffs, export controls, investment policy, industrial policy, tax, data, AI, telecom, pharma, defence, semiconductors, energy, or infrastructure issues.
4. Investing in nearby competitor destinations such as Vietnam, Japan-linked Asia expansion, Australia-India flows, or EU/UK policy corridors in a way that creates a human BD prompt: "should TAG pitch India now?"

The system is not intended to fully automate target selection. It should produce evidence-backed candidate rows for human review.

## 2. Core User Story

As a TAG BD operator, I want a weekly Sheet 7 feed of companies with public evidence of India interest, China+1 movement, or India-related lobbying, so that I can review the source context, decide whether the signal is real, and move qualified companies into a human-led outreach workflow.

## 3. Non-Goals

- Do not scrape confidential, paywalled, or private registers.
- Do not treat macro-only flows as named company leads.
- Do not auto-email prospects.
- Do not make legal or investment conclusions from filings.
- Do not store API keys in the repo, Google Sheet, or source text.
- Do not build a brittle browser scraper where a stable API, feed, or downloadable dataset exists.

## 4. Required Secret and Config Handling

The original scratch file contained plaintext keys. Darsh says these were not publicly disclosed, so rotation is not mandatory right now. Still, do not commit, paste, or upload them anywhere else.

Plaintext secrets seen in the scratch file:

- U.S. LDA API key.
- Two Companies House API keys.
- LSE RNS API key.

Before build, move the current keys to environment variables. Rotate only if any key was committed to Git, shared in a public doc, pasted into a third-party issue/PR, or otherwise exposed outside private working context.

Required before production run:

- `SEC_USER_AGENT`: SEC-required identity string, e.g. `TAG Intelligence darsh@example.com`.
- `LDA_API_KEY`: U.S. Lobbying Disclosure Act API key. Use the new `lda.gov` host.
- `COMPANIES_HOUSE_API_KEY`: UK Companies House API key.
- `EDINET_API_KEY`: Japan EDINET Subscription-Key.

Optional:

- `JQUANTS_API_KEY`: only if market reaction data is added.
- `EODHD_API_KEY`: only if paid ASX company-level data is approved.
- `LSE_RNS_API_KEY`: only if the exact provider docs for the existing RNS key are supplied and verified.
- `DATA_GOV_IN_API_KEY`: India OGD/data.gov.in key for MCA and other India datasets.
- `EPO_OPS_CLIENT_ID` and `EPO_OPS_CLIENT_SECRET`: EPO OPS OAuth credentials for patent data.
- `LENS_API_TOKEN`: Lens Patent API bearer token.
- `USPTO_API_KEY`: only if a USPTO endpoint used in the build requires it.

Implementation rule: all connectors read secrets through env vars or a secret manager. The build must include a `.env.example` with variable names only.

## 5. Country Source Stack

For each country, scan company disclosures first, then lobbying/policy disclosures, then news or macro context. Every source should scan for India, China+1, supply-chain relocation, manufacturing expansion, South Asia, capex, market-entry, and relevant policy/lobbying language.

### India

India is the landing layer for Sheet 7. It does two jobs: resolve named Indian entities and add India-origin signals such as IP filings, domestic corporate announcements, consultations, and lobbying proxies.

#### A. Company/Entity Disclosures - MCA Company Master Data

Purpose: India entity spine. This is the table that lets signals from SEC, EDINET, Companies House, EU meetings, patents, and RSS resolve into actual Indian entities instead of loose company-name guesses.

Source:

- Dataset: `https://www.data.gov.in/catalog/company-master-data`
- OGD API base: `https://api.data.gov.in/`

Machine-usable facts:

- The Company Master Data catalog is contributed by the Ministry of Corporate Affairs and contains CIN, company name, company status, company class, company category, authorized capital, paid-up capital, date of registration, registered state, RoC, principal business activity, and registered office fields.
- The catalog page exposes a Catalog API and ZIP download path. The page was updated on 2026-06-11.

Auth/rate requirements:

- Free data.gov.in API key.
- Store as `DATA_GOV_IN_API_KEY`.

Implementation:

1. Pull MCA Company Master Data first, before trying to enrich any India-related signal.
2. Key on CIN when available.
3. Maintain normalized company name, CIN, RoC, state, company status, registration date, and business activity.
4. Use MCA as entity support, not as a standalone BD trigger. A company existing in India is context; a filing, patent, consultation, announcement, or policy signal is the trigger.
5. Use this spine to match foreign parent names to Indian subsidiaries only when the name match is strong or backed by source evidence.

#### B. IP Filings - WIPO Discovery, EPO OPS, and Lens

Purpose: IP filings are a leading market-entry indicator. A foreign company filing patents in India, entering Indian national phase, assigning India-related patent rights, or repeatedly protecting India-facing technology can signal commercial intent before a public expansion announcement.

Source stack:

- WIPO API Catalog, discovery only: `https://apicatalog.wipo.int/`
- EPO Open Patent Services: `https://ops.epo.org/3.2/rest-services`
- EPO OPS product/docs page: `https://www.epo.org/en/searching-for-patents/data/web-services/ops`
- Lens Patent API docs: `https://docs.api.lens.org/`
- Lens patent search endpoint: `https://api.lens.org/patent/search`

EPO OPS notes:

- OPS is a RESTful web service over EPO bibliographic, worldwide legal event, full-text, and image databases.
- EPO says OPS uses OAuth credentials and has a non-paying tier up to 4 GB/week; paid access is for higher usage.
- Use for DOCDB/INPADOC-style worldwide bibliographic and legal-event coverage, including India-relevant patent-family and national-phase signals.

Lens notes:

- Lens API gives REST access to patent and scholarly corpora.
- Patent API supports fields such as jurisdiction, publication date, application reference, priority claim, applicant name, owner, legal status, full text, and family members.
- Use bearer-token auth with `Authorization: Bearer <token>`.

Implementation:

1. Query by applicant/owner names from target companies and by India-related patent jurisdictions/family members.
2. Capture publication/application dates, applicant, owner, jurisdiction, family members, legal status, title, abstract, claims snippet, and source URL.
3. Flag signals such as Indian national phase, Indian publication/grant, India family member, India-resident applicant/owner, or repeated recent filings in India-relevant classes.
4. Join applicant/owner names to MCA when an Indian subsidiary exists.
5. Treat patent filings as `india_ip_market_entry` signals, not proof of operating presence.

Trademark gap:

- WIPO Global Brand Database and Madrid Monitor are useful human research tools but should not be automated unless their terms and bulk-access permissions are explicitly cleared.
- Indian Patent/Trademark Registry direct search is not approved for v1 because there is no clean stable API in the current PRD.
- Do not pretend trademark coverage is solved.

Dropped/limited:

- WIPO PATENTSCOPE API is not the v1 path. Use WIPO API Catalog for discovery, EPO OPS/Lens for machine retrieval, and revisit PATENTSCOPE only if paid SOAP access is approved.

USPTO optional enrichment:

- USPTO Developer Portal: `https://developer.uspto.gov/`
- Role: U.S.-side IP enrichment only, not a replacement for EPO OPS or Lens.
- Use only when the record is India-related: India family member, Indian national phase, Indian assignee/owner/inventor address, India mentioned in title/abstract/claims/assignment text, or an India-facing trademark/brand signal.
- Useful fields/signals: U.S. assignee normalization, assignment events, patent ownership changes, and trademark filings that mention India-facing products or Indian entities.
- Do not add broad USPTO monitoring. Sheet 7 does not need every U.S. patent by a target company.

#### C. Company Disclosures - Indian Corporate Announcements

Purpose: listed Indian company announcements can confirm M&A, JV, capex, manufacturing expansion, India operations, or foreign partner activity after the earliest IP/entity signal.

Source stack:

- Official NSE structured feeds are paid.
- BSE Python wrapper: `https://github.com/BennyThadikaran/BseIndiaApi`
- NSE+BSE TypeScript wrapper: `https://github.com/bshada/nse-bse-api`

Status:

- Best-effort only. These wrappers rely on exchange-facing/internal endpoints and can break without notice.
- Reliable structured access requires paid NSE/BSE data products.

Implementation:

1. Treat as Tier B until the official/paid path is chosen.
2. Scan announcements for M&A, JV, capex, expansion, plant/factory, foreign partner, investment, supply-chain, and China+1 language.
3. Join listed company names to MCA where possible.

#### D. Lobbying/Policy Proxies - No India Lobbying Register

India has no lobbying disclosure regime. Do not invent a source called "India lobbying filings." Use proxy footprints and label them honestly.

Consultation responses:

- Strongest proxy. Who files comments on MeitY, TRAI, DPIIT, tax, telecom, AI, data, pharma, energy, defence, or industrial-policy consultations is the closest machine-visible lobbying act.
- This is already partly in the regulatory tracker; extend entity extraction to capture commenter names and match them to MCA/foreign parents.

PRS Legislative Research:

- Site: `https://prsindia.org/`
- Bills track: `https://prsindia.org/billtrack`
- Community dataset: `https://github.com/Vonter/india-representatives-activity`
- Role: committee reports, bill pages, and public evidence can identify named bodies, industry groups, or firms participating in policy formation. Use as policy context, not as a canonical lobbying register.

Industry associations:

- CII, FICCI, ASSOCHAM, NASSCOM and sector bodies publish pre-budget memoranda and consultation submissions.
- Treat as scrape targets only where publication pages are stable and terms permit.
- These often reveal the lobbying vehicle even when individual firms are not named.

Electoral bonds:

- ECI disclosure page: `https://www.eci.gov.in/disclosure-of-electoral-bonds`
- Historical backfill only. The scheme was struck down in 2024, so this is not a live feed.
- Use for one-time relationship mapping, not weekly Sheet 7 monitoring.

#### E. Dropped India/WIPO Sources

- API Setu: identity/verification gateway, not a BD intelligence source.
- WIPO Global Brand Database and Madrid Monitor: human research only unless automated/bulk access is explicitly cleared.
- Indian Patent/Trademark Registry direct scraping: no clean approved API for v1.
- Electoral bonds as live feed: static historical source only.

### United States

#### A. Company Disclosures - SEC EDGAR

Purpose: detect 10-K, 10-Q, 8-K, 20-F, 6-K, and related filings mentioning India, China+1, supply chain relocation, manufacturing expansion, South Asia, and capex/investment intent.

Supported SEC APIs and data:

- Company submissions JSON: `https://data.sec.gov/submissions/CIK##########.json`
- Company facts JSON: `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`
- Company concept JSON: `https://data.sec.gov/api/xbrl/companyconcept/CIK##########/{taxonomy}/{tag}.json`
- Bulk submissions ZIP: `https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip`
- Bulk company facts ZIP: `https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip`
- Filing text pattern: `https://www.sec.gov/Archives/edgar/data/{cik_no_leading_zeroes}/{accession_no_no_dashes}/{accession_no}.txt`

Full-text discovery endpoint:

- `https://efts.sec.gov/LATEST/search-index`

Engineering note: SEC documents the `data.sec.gov` APIs for submissions and XBRL. The `efts.sec.gov` endpoint is the public full-text search backend, useful for keyword discovery, but should be wrapped with retry/backoff and treated as less stable than the official filing/archive APIs.

Auth/rate requirements:

- No API key.
- Must send a real `User-Agent` identity in every request.
- Respect SEC fair-access behavior. Start with max 5 requests/second globally, exponential backoff on 429/403, and cache raw filings.

Implementation:

1. If running broad discovery, query `efts.sec.gov/LATEST/search-index` for keyword phrases and target forms.
2. For each hit, normalize CIK, accession number, form, filing date, company name, filing URL, and highlights.
3. Fetch canonical filing text from SEC Archives when needed.
4. Extract evidence windows around matched terms.
5. Score based on proximity between India terms and action terms such as invest, expand, manufacture, facility, plant, supply chain, subsidiary, acquisition, capex, regulatory approval, customer, or market entry.

#### B. Lobbying Disclosures - Lobbying Disclosure Act

Purpose: detect companies, clients, or registrants lobbying on India-related trade, tariff, foreign affairs, tax, technology, pharma, defence, energy, telecom, AI, data, semiconductor, and market-access issues.

Canonical host:

- API home: `https://lda.gov/api/`
- Docs: `https://lda.gov/api/redoc/v1/`
- Filings: `https://lda.gov/api/v1/filings/`
- Contributions: `https://lda.gov/api/v1/contributions/`
- Registrants: `https://lda.gov/api/v1/registrants/`
- Clients: `https://lda.gov/api/v1/clients/`
- Lobbyists: `https://lda.gov/api/v1/lobbyists/`

Important date:

- The old `https://lda.senate.gov` host says it will no longer be available after 2026-06-30. Build against `https://lda.gov`, not the Senate legacy host.

Auth/rate requirements:

- API key supported: 120 requests/minute.
- Anonymous allowed: 15 requests/minute.
- Store the key as `LDA_API_KEY`.

Implementation:

1. Poll filings weekly for recent LD-1/LD-2 filings.
2. Query/filter by issue text and specific words: India, Indian, Indo-Pacific, South Asia, tariffs, USTR, market access, export controls, supply chain, China, manufacturing, customs, trade, data localization, digital trade.
3. Normalize client, registrant, filing year, period, issue codes, issue text, amount, filing URL, and source retrieval date.
4. Map client names to the company/entity spine.

### Canada

#### A. Company Disclosures - SEDAR+ and Federal Corporations

SEDAR+ use case: Canadian issuer filings mentioning India or China+1.

SEDAR+ status: not a clean public API. The public interface may allow CSV export from search results, but access can be blocked and should not be treated as a stable API.

SEDAR+ build only if approved:

1. Use Playwright in a low-frequency weekly job.
2. Submit document-content searches for India, South Asia, China+1, supply-chain relocation, manufacturing expansion, and capex/investment intent.
3. Trigger official CSV export if the interface allows it.
4. Store screenshots/logs for failure diagnosis.
5. Stop immediately if blocked by terms, bot protections, or access warnings.

Federal Corporations purpose: entity-spine support, not a primary BD signal.

Machine-usable discovery route:

- Open Canada CKAN-style search: `https://open.canada.ca/data/api/action/package_search?q=federal%20corporations`

Implementation:

1. Resolve the current Federal Corporations dataset resource URL at runtime.
2. Download CSV if present.
3. Use it for Canadian entity matching, incorporation recency, and name normalization.
4. Do not treat incorporation alone as a high-confidence India expansion signal.

#### B. Lobbying Disclosures - Office of the Commissioner of Lobbying

Purpose: detect Canada federal lobbying communications and registrations tied to India, trade, tariffs, foreign affairs, industrial policy, or target multinationals.

Machine-usable files:

- Open data page: `https://lobbycanada.gc.ca/en/open-data/`
- Lobbying registrations ZIP: `https://lobbycanada.gc.ca/media/zwcjycef/registrations_enregistrements_ocl_cal.zip`
- Monthly communication reports ZIP: `https://lobbycanada.gc.ca/media/mqbbmaqk/communications_ocl_cal.zip`

Auth/rate requirements:

- No key.
- Weekly download is sufficient.

Implementation:

1. Download both ZIP files weekly.
2. Parse primary and secondary CSVs plus dictionaries.
3. Filter communication reports by subject matter and text fields.
4. Join registrations to communications where identifiers allow.
5. Output named client/organization and public office holder context where present.

### United Kingdom

#### A. Company Disclosures - Companies House and LSE RNS

Companies House purpose: UK entity spine plus filing-text discovery. Companies House is not a primary lobbying source, but annual reports and filing documents can contain India, China+1, supply-chain, and market-entry language.

Companies House docs and endpoints:

- Developer hub: `https://developer.company-information.service.gov.uk/`
- Public Data API specs: `https://developer-specs.company-information.service.gov.uk/`
- Company search: `https://api.company-information.service.gov.uk/search/companies?q={query}`
- Company profile: `https://api.company-information.service.gov.uk/company/{company_number}`
- Filing history: `https://api.company-information.service.gov.uk/company/{company_number}/filing-history`
- Officers: `https://api.company-information.service.gov.uk/company/{company_number}/officers`
- PSCs: `https://api.company-information.service.gov.uk/company/{company_number}/persons-with-significant-control`
- Document content: `https://document-api.company-information.service.gov.uk/document/{document_id}/content`

Companies House auth:

- HTTP Basic auth.
- API key is username; password blank.
- Store as `COMPANIES_HOUSE_API_KEY`.

Companies House implementation:

1. Use target-company names from other sources to search Companies House.
2. Pull profile, filing history, officers, PSCs, and document metadata for matching.
3. For filing types that expose PDF or HTML document content, scan the text for the Sheet 7 keyword set.
4. Do not over-weight UK incorporation alone. A UK row needs either India/China+1 text, a relevant filing document, or a match to a named target from another source.

LSE RNS source:

- Human-facing live feed: `https://www.londonstockexchange.com/news?tab=today-s-news`

LSE RNS status: do not build from the pasted key until the exact third-party provider documentation is supplied and verified. If the key belongs to a paid RNS API, add its base URL, rate limits, query syntax, and license constraints before implementation.

#### B. Lobbying Disclosures - ORCL and UKLR

Sources:

- ORCL site: `https://registrarofconsultantlobbyists.org.uk/`
- UK Lobbying Register: `https://www.lobbying-register.uk/`

Status: useful, but not clean API-first sources. Add after U.S./Canada/EU lobbying works.

### European Union

#### A. Company/Register Disclosures - Transparency Register

Purpose: identify EU-registered entities, declared policy files, declared lobbying spend/FTE, country, and Transparency Register IDs that mention India, South Asia, China+1, trade, supply chains, market access, digital regulation, industrial policy, antitrust, or geopolitical corridors.

Source:

- Transparency Register dataset: `https://data.europa.eu/data/datasets/transparency-register`
- data.europa.eu hub API: `https://data.europa.eu/api/hub/search/`
- data.europa.eu dataset repo API: `https://data.europa.eu/api/hub/repo/datasets`

Implementation:

1. Use the hub API to resolve current download/distribution URLs instead of hardcoding rotating dataset files.
2. Search declared EU files, organization names, and free-text fields for India and adjacent terms.
3. Use Transparency Register ID as the EU spine.

#### B. Lobbying/Meetings - Commission Meetings and EP API

Purpose: detect stakeholder meetings and parliamentary activity tied to India, trade, supply chains, market access, digital regulation, industrial policy, antitrust, or geopolitical corridors.

Build against official sources:

- Commission meetings dataset: `https://data.europa.eu/data/datasets/european-commission-meetings-with-interest-representatives`
- European Parliament Open Data API v2: `https://data.europarl.europa.eu/api/v2`

Implementation:

1. Join Commission meetings to Transparency Register records by Transparency Register ID.
2. Search meeting subjects, declared files, organization names, and free-text fields for India and adjacent terms.
3. Add EP API only after Commission + Transparency Register join works.

Skip for production pipeline:

- Integrity Watch: useful human research interface, not a production API.
- LobbyFacts old API: archived/replaced; do not build against it.

### Japan

#### A. Company Disclosures - EDINET

Purpose: company-level Japanese corporate disclosure feed for filings that mention India, production bases, overseas manufacturing, China+1, restructuring, subsidiaries, acquisitions, capex, or supply-chain relocation.

Official docs and endpoints:

- API documentation page: `https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/WEEK0060.html`
- Document list: `https://api.edinet-fsa.go.jp/api/v2/documents.json?date=YYYY-MM-DD&type=2`
- Document fetch: `https://api.edinet-fsa.go.jp/api/v2/documents/{docID}?type=5`
- Registration: `https://disclosure2.edinet-fsa.go.jp/`
- Python SDK: `https://github.com/matthelmer/edinet-tools`

Auth/rate requirements:

- Free Subscription-Key.
- Store as `EDINET_API_KEY`.
- Throttle to at least 3 seconds between requests unless official docs say otherwise.

Implementation:

1. Use `edinet-tools` plus the free API key.
2. Pull daily document lists.
3. Fetch relevant document types:
   - 120/130 Securities Reports.
   - 180/190 Extraordinary Reports.
   - 240/250 Tender Offer Registration if M&A is relevant.
   - 350/360 Large Shareholding only for ownership-trigger signals.
4. Search Japanese and English keyword sets:
   - India, インド, South Asia, 南アジア.
   - China+1, China plus one, supply chain, サプライチェーン.
   - production base, manufacturing base, 生産拠点, 工場, 製造, 設備投資.
5. Output company name, EDINET code, ticker if resolvable, doc type, filing date, source URL, matched language, and context window.

#### B. Lobbying Disclosures

No clean Japan lobbying-disclosure source is approved for v1. Do not invent one.

### Australia

#### A. Company Disclosures - ASX Announcements

Purpose: best-effort company-level signal. Australia does not provide a free EDINET-equivalent company-disclosure API.

Best-effort or paid company-level source:

- ASX announcements HTML: `https://www.asx.com.au/asx/v2/statistics/announcements.do?by=asxCode&timeframe=D&period=M6&asxCode={CODE}`
- Paid structured fallback: `https://eodhd.com/asx-data`

Implementation:

1. Treat ASX HTML as fragile and optional.
2. If Australia company-level evidence matters, require explicit approval for a paid provider such as EODHD.
3. Scan announcements for India, China+1, supply-chain relocation, manufacturing expansion, South Asia, capex, and market-entry language.

#### B. Lobbying/Public Policy Disclosures

No clean Australia outbound-investment or lobbying-disclosure source is approved for v1.

Drop:

- FIRB intent documents: no public feed and wrong direction for outbound Australia-to-Asia targeting.

#### C. Macro Context - ABS and data.gov.au

Purpose: macro context only. These sources do not produce named company leads.

Free machine-usable sources:

- ABS API guide: `https://www.abs.gov.au/statistics/application-programming-interfaces-apis/data-api-user-guide`
- ABS API base: `https://data.api.abs.gov.au/rest/`
- ABS dataflows: `https://data.api.abs.gov.au/rest/dataflow/all?detail=allstubs`
- data.gov.au CKAN action API: `https://data.gov.au/data/api/3/action/`
- data.gov.au foreign investment search: `https://data.gov.au/data/api/3/action/package_search?q=foreign+investment`

Implementation:

1. Use ABS and data.gov.au for macro trend context only.
2. Do not present macro-only rows as company leads.

### Vietnam

#### A. Company/Project Disclosures

No clean government company-level project API is approved for v1.

Government aggregate:

- Foreign Investment Agency portal: `https://fia.mpi.gov.vn/`

Implementation:

1. Use FIA/MPI only for aggregate monthly trend context if stable pages are available.
2. Do not expect a government company-level project API.

#### B. News/RSS Company Signal

Purpose: detect companies choosing Vietnam, especially where the pitch angle is "India should be reconsidered" or "TAG can help compare India/Vietnam."

Machine-usable feeds:

- Vietnam Investment Review RSS: `https://vir.com.vn/rss`
- Vietnam Briefing RSS: `https://www.vietnam-briefing.com/news/feed`
- VnExpress International Business RSS: `https://e.vnexpress.net/rss/business.rss`

Implementation:

1. Parse RSS feeds daily.
2. Extract company names, countries, sectors, industrial parks, provinces, and investment amounts from article text.
3. Use these rows as competitor-market or China+1 comparison signals, not official government filings.

## 6. Cross-Country Fragile and Research-Only Rules

These can be added after the core country stack works, with explicit acceptance of fragility.

### Scrapling Policy for Lobbying Sites

Question: should the project integrate `https://github.com/D4Vinci/Scrapling` for high-level scraping of Integrity Watch or LobbyFacts?

Decision: no for the production pipeline. Scrapling can be evaluated only as a research-only fallback after the official EU sources are implemented.

Reason:

- Integrity Watch's European Commission meetings view is a research UI over data that should be pulled from official sources: Transparency Register plus Commission meetings datasets.
- LobbyFacts is a downstream research interface over EU Transparency Register data and historical enrichments; it should not replace the official register and data.europa.eu pipeline.
- Scrapling advertises anti-bot bypass, proxy rotation, and stealth fetchers. Those features create compliance, reliability, and reputational risk for a business-data PRD.
- A scraper tied to page structure is harder to test and maintain than the official data distribution URLs.

Allowed use, if explicitly approved later:

1. Put Scrapling code under `research_only/scrapers/`, not `connectors/`.
2. Disable stealth, proxy rotation, CAPTCHA solving, and anti-bot bypass modes.
3. Respect robots.txt, crawl delay, site terms, and low request rates.
4. Cache every fetched page and record retrieval timestamps.
5. Never promote a research-only scraped row to Sheet 7 unless the same signal can be backed by an official source URL or clearly labeled as research-only.

Preferred implementation:

- Use `data.europa.eu` hub APIs to resolve current Transparency Register and Commission meetings files.
- Use the European Parliament Open Data API for parliamentary activity.
- Treat Integrity Watch and LobbyFacts as human QA/research cross-checks, not pipeline sources.

## 7. Data Model

Each connector writes normalized disclosure events into a small common schema. Keep v1 narrow; add fields only when reviewers repeatedly need them.

Required fields:

- `event_id`: stable deterministic hash of source, source record id, company, date, and match term.
- `source`: enum: india_mca, epo_ops, lens_patents, uspto_ip, india_corporate_announcements, india_consultations, prs_india, india_associations, electoral_bonds, sec, lda_us, ocl_canada, companies_house, eu_transparency, eu_commission_meetings, eu_parliament, edinet, abs_au, data_gov_au, asx_html, vir, vietnam_briefing, vnexpress, fia_vietnam.
- `country_system`: US, CA, UK, EU, JP, AU, VN.
- `company_name`.
- `document_type`.
- `filing_date`.
- `retrieved_at`.
- `source_url`.
- `evidence_text`.
- `matched_terms`.
- `score`: 0-100 composite score.
- `confidence`: low, medium, high.
- `human_review_status`: new, reviewed, accepted, rejected, needs_research.

Optional later fields:

- `company_identifiers`: add after entity matching is real, not guessed.
- `evidence_language`: add if Japanese/English review routing matters.
- `review_notes`: add when the Sheet is actively reviewed.
- Split scores: add only if reviewers ask to distinguish India relevance from actionability.

Do not include `parent_company_guess` in v1. Guesses look authoritative and will be trusted when wrong.

## 8. Keyword Taxonomy

Scan every country/source for India and China+1 language. Do not limit India scanning to U.S. or Japan filings.

Keep keywords configurable in `config/sheet7_keywords.yml`, but use them only as a high-recall retrieval layer. Keywords decide what text windows to inspect; they do not decide whether a row is a real BD signal.

India terms:

- India, Indian, Bharat, South Asia, Indo-Pacific, インド, 南アジア.

China+1 terms:

- China+1, China plus one, China Plus One, supply chain diversification, supply-chain resilience, derisking, de-risking, nearshoring, friendshoring, reshoring, relocation, manufacturing shift, production transfer.

Action terms:

- invest, investment, capex, capital expenditure, expand, expansion, new facility, plant, factory, manufacturing, production base, subsidiary, branch, office, regional hub, acquisition, joint venture, memorandum, MoU, tender offer, restructuring.

Policy/lobbying terms:

- USTR, tariff, customs, market access, foreign affairs, trade, export controls, sanctions, FDI, data localization, digital trade, AI, telecom, pharma, medical devices, defence, semiconductors, energy, infrastructure, tax treaty.

IP/market-entry terms:

- patent, patent application, PCT, national phase, India national phase, publication, grant, applicant, assignee, owner, trademark, brand, Madrid, intellectual property, IP filing.

Japanese terms:

- インド, 生産拠点, 工場, 製造, 設備投資, 子会社, 買収, 供給網, サプライチェーン, 中国.

## 9. Signal Classification

Do not hardcode final relevance with word rules. Use a two-step, non-generative classification pipeline:

1. Retrieval: use broad keyword/regex/section filters to find candidate evidence windows across filings, lobbying text, RSS, and disclosure documents.
2. Classification: run both Option A and Option B locally in Python, compare their outputs, and route disagreements to human review.

Option A - prototype embedding classifier:

- Use `sentence-transformers` to embed the evidence window.
- Compare it to hand-written prototype examples for each label.
- Use multilingual embeddings so Japanese EDINET windows can be compared with English prototypes.
- Recommended model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.

Option B - zero-shot classifier:

- Use Hugging Face `transformers` zero-shot classification.
- Candidate labels should match the Sheet 7 labels below.
- Recommended starting model: `facebook/bart-large-mnli` for English-heavy sources.
- For multilingual windows, either translate the evidence window first or use a multilingual NLI model if accuracy is acceptable in testing.

Agreement gate:

- If Option A and Option B choose the same non-noise label, promote the row when the blended score is >= 60.
- If both choose `boilerplate_or_noise`, keep the row out of Sheet 7 and retain it only in raw cache.
- If they disagree, send the row to Sheet 7 with `confidence=low` and `human_review_status=needs_research`, unless one classifier is very confident and the other is only weakly opposed.
- Blended score: `round((embedding_score * 0.45) + (zero_shot_score * 0.45) + source_reliability_bonus)`, capped at 100.

Classifier output:

- `is_relevant`: true/false.
- `signal_label`: india_interest, india_investment, india_ip_market_entry, india_entity_spine, china_plus_one, india_policy_lobbying, india_risk_or_friction, chose_competitor_market, boilerplate_or_noise.
- `polarity`: positive, negative, mixed, neutral.
- `score`: 0-100.
- `confidence`: low, medium, high.
- `reason`: one short sentence grounded only in the evidence text.

Positive and negative mentions both matter if they indicate real interest or decision-making about India. Examples:

- Positive: company is investing in India, opening a plant, hiring, acquiring, lobbying for market access, or naming India as a growth market.
- Negative but relevant: company delayed India investment, chose Vietnam over India, cites India regulatory barriers, lobbies on India tariffs, or describes India as a material risk to a planned expansion.
- Noise: boilerplate country lists, generic risk-factor lists, one-off customer mentions, or "India" appearing without action, policy, investment, supply-chain, or strategic context.

Only `is_relevant=true` rows enter the main Sheet 7 view. Disagreements enter Sheet 7 only as `needs_research`. Rejected rows can stay in raw cache for audit.

## 10. Scoring Rules

Initial score can be deterministic. Do not require an LLM for v1.

High confidence:

- Company-resolved filing or lobbying record.
- India term within 500 characters of action/policy term.
- Source is SEC, LDA, OCL Canada, Companies House filing, EU official dataset, EDINET, India IP filing, or India consultation/policy evidence.
- Evidence text directly states investment, expansion, lobbying subject, manufacturing, acquisition, or market-entry intent.
- MCA match increases confidence when it resolves the entity, but MCA existence alone is not a BD signal.

Medium confidence:

- RSS article names a company and India/Vietnam/China+1 context.
- Macro source supports trend but does not name companies.
- Company is identified but action is indirect.

Low confidence:

- Generic mention of India as a market risk.
- Boilerplate geographic list.
- Macro-only flow without company name.
- Registry change without India or strategy context.

Composite score components:

- Source reliability: 0-30.
- Company resolution quality: 0-20.
- India/proximity match: 0-25.
- Actionability: 0-15.
- Recency: 0-10.

Rows with `score < 40` should remain in raw events but not be pushed to the primary Sheet 7 view unless explicitly requested.

## 11. Pipeline Architecture

Recommended implementation in Python:

- `connectors/`: one connector per source.
- `normalizers/`: source-specific to common schema.
- `scoring/`: keyword proximity and confidence.
- `storage/`: raw cache plus normalized event file.
- `sheet_writer.py`: CSV and Google Sheets write function.
- `tests/fixtures/`: one sample response per source.

Entity matching v1:

- Normalize company names with lowercase, punctuation stripping, legal suffix stripping, whitespace collapse, and alias map overrides.
- Prefer official IDs when present: CIK, EDINET code, Companies House number, Transparency Register ID.
- Use fuzzy matching only for review hints, not automatic parent assignment.
- Do not create a separate entity-resolution module until at least two Tier A connectors are producing real rows.

Recommended libraries:

- `httpx` or `requests` for HTTP.
- `tenacity` for retry/backoff.
- `pydantic` for normalized schema validation.
- `pandas` or `polars` for CSV-heavy datasets.
- `feedparser` for RSS.
- `beautifulsoup4` and `lxml` for approved HTML sources only.
- `playwright` only for Tier B browser flows.
- `edinet-tools` for EDINET.
- `sentence-transformers` for Option A prototype similarity.
- `transformers` and `torch` for Option B zero-shot classification.
- `python-dotenv` for local development only.

Storage:

- Raw immutable files: `data/raw/{source}/{YYYY-MM-DD}/...`
- Normalized events: local JSONL or CSV for v1.
- Export file: `sheet7_candidates_{run_date}.csv`.
- Google Sheets: write to the live Sheet 7 tab first.
- Supabase/Postgres: defer until Sheets 1-7 prove the columns and review workflow.
- Keep raw evidence so every Sheet 7 row is auditable.

Public repo rule:

- Public repo may include connector code, prototype examples, test fixtures with redacted/synthetic text, and model configuration.
- Do not commit API keys, `.env`, downloaded raw filing caches, Google credentials, or private review notes.

## 12. Google Sheets Output

V1 writes to Google Sheets first and also saves a local CSV backup. Vercel and Supabase come later, after Sheets 1-7 settle.

Sheet 7 recommended columns:

1. `Run Date`
2. `Signal Date`
3. `Company`
4. `Country/System`
5. `Source`
6. `Document Type`
7. `India/China+1 Thesis`
8. `Evidence Snippet`
9. `Source URL`
10. `Matched Terms`
11. `Score`
12. `Confidence`
13. `Human Review Status`
14. `Notes`

Suggested human next steps:

- Research India presence.
- Check parent/subsidiary structure.
- Compare India vs Vietnam decision.
- Draft TAG outreach angle.
- Reject as boilerplate.

## 13. Build Sequence

The project should still be implemented as a staged engineering plan. Keep the PRs small enough to review, but do not collapse the whole source stack into one build.

PR 1 - Foundation:

- Add env handling and `.env.example`.
- Add the normalized event schema.
- Add keyword config.
- Add raw cache.
- Add deterministic `event_id` de-duplication.
- Add composite scoring.
- Add CSV backup export.
- Add the Google Sheets writer that appends new rows and preserves existing `Human Review Status` / `Notes`.
- Add MCA Company Master Data loader as the India entity spine.
- Add one runnable self-check or small test for schema, scoring, and de-duplication.

PR 2 - United States:

- SEC connector.
- LDA connector using `https://lda.gov`, not `https://lda.senate.gov`.
- Fixtures for one SEC filing and one LDA filing response.
- Sheet 7 dry-run output for U.S. sources.

PR 3 - Japan:

- EDINET connector using `edinet-tools`.
- Enforce `EDINET_API_KEY` for document fetching.
- Japanese and English keyword scanning.
- Fixtures for document list and one fetched document.
- Add India IP connector path with EPO OPS and Lens if credentials are available.
- Join India IP applicant/owner names to MCA where possible.

PR 4 - Canada and UK:

- Canada OCL open-data connector.
- Canada Federal Corporations discovery connector for entity support.
- Companies House connector.
- Companies House filing-text scan for India/China+1 language.
- Keep entity matching conservative: official IDs and normalized names only, no parent guessing.

PR 5 - European Union:

- data.europa.eu discovery helper.
- Transparency Register dataset pull.
- Commission meetings dataset pull.
- Join meetings to Transparency Register by Transparency Register ID.
- Search subjects, files, and organization fields for India and adjacent policy terms.
- Keep Integrity Watch and LobbyFacts as human QA/research cross-checks only.

PR 6 - APAC Complements and Production Polish:

- Vietnam RSS connectors: VIR, Vietnam Briefing, VnExpress International Business.
- Australia ABS/data.gov.au macro connectors.
- India corporate-announcement best-effort connector only if unofficial exchange-wrapper fragility is accepted.
- India lobbying proxies: consultation responses first, PRS/association sources only as research/secondary context.
- Optional ASX/EODHD connector only if paid source is approved.
- Final Google Sheets de-dupe and review-status preservation.
- README with setup, keys, rate limits, caveats, and run commands.
- Production dry run across enabled sources.

## 14. Acceptance Criteria

Functional:

- Running `python -m sheet7_pipeline run --since YYYY-MM-DD --sources sec,lda_us,edinet` produces a valid CSV.
- Every output row has a source URL and evidence snippet.
- Every high-confidence row has a named company.
- Macro-only rows are marked as macro context and do not masquerade as company leads.
- Duplicate events are suppressed by deterministic `event_id`.
- All secrets are read from environment variables.
- The Google Sheets writer can append new rows without overwriting human review fields.

Source-specific:

- MCA connector can fetch or load Company Master Data and emit CIN-backed entity rows.
- EPO OPS or Lens connector can fetch at least one India-relevant patent record when credentials are present.
- SEC connector can fetch a known company submissions JSON and at least one filing text.
- LDA connector uses `https://lda.gov`, not `https://lda.senate.gov`.
- Canada OCL connector can download and parse the communications ZIP.
- Companies House connector authenticates via Basic auth with key as username.
- EDINET connector refuses to run without `EDINET_API_KEY` for document fetches.
- Vietnam RSS connector parses at least title, link, published date, summary, and source.

Quality:

- Tests cover schema validation, scoring, de-duplication, and at least one fixture per connector.
- Integration tests can run with `--dry-run` and skip sources whose keys are missing.
- The README explains key setup, rate limits, source caveats, and build order.

## 15. Open Decisions for Darsh

1. Rotate burned keys before build: `LDA_API_KEY`, `COMPANIES_HOUSE_API_KEY`, and any LSE RNS key.
2. Provide `DATA_GOV_IN_API_KEY` for MCA/data.gov.in.
3. Provide EPO OPS credentials and/or Lens Patent API token if India IP is included in v1.
4. Confirm whether USPTO should be added as optional India-related IP enrichment, and provide `USPTO_API_KEY` if the chosen endpoint requires it.
5. Provide `EDINET_API_KEY` if Japan is included in v1.
6. Choose the live Google Sheet: `TAGTRIAL`, `TAGTRIAL2`, or a new spreadsheet.
7. Confirm whether Sheet 3 is dead so the engineer does not build joins against it.
8. Confirm whether paid ASX company-level data is worth it. If yes, use EODHD or another licensed provider; do not depend on fragile ASX HTML as the main path.
9. Confirm whether SEDAR+ browser automation is acceptable despite fragility and possible blocking.
10. Confirm whether unofficial NSE/BSE wrappers are acceptable as best-effort only, or whether Indian exchange announcements should wait for a paid official feed.
11. Provide exact docs for the LSE RNS key before any engineer builds that connector.

## 16. Engineering Warnings

- Do not commit secrets.
- Do not build against deprecated `lda.senate.gov` links.
- Do not treat LobbyFacts, Integrity Watch, FIRB, investvietnam.vn, or SEDAR+ as clean APIs.
- Do not treat WIPO Global Brand Database, Madrid Monitor, or Indian IP registry pages as approved automated sources.
- Do not overfit to one keyword. Boilerplate mentions of India are common in 10-K risk sections.
- Keep raw evidence because the human reviewer needs to trust the row.
- Entity resolution is the real bottleneck. The scraper finds signals; the entity spine turns those signals into BD targets.
- Do not spend Supabase limits until Google Sheets proves the Sheet 7 schema and review loop.
