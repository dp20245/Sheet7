# Sheet7 — Public Disclosures Intent Engine — Build Specification

**Owner:** Darsh Puri
**Component:** Sheet7 of the TAG Cross-Border BD Intelligence system — the public-disclosures intent engine.
**Purpose:** Ingest public filings, lobbying records, and IP disclosures; deterministically rank them for India/China+1/market-entry relevance; use a single LLM layer to judge intent and tense; promote genuine BD-actionable signals to a reviewed-signals tab.
**Storage:** Google Sheets (spreadsheet `TAGTRIAL7`). Postgres/Supabase migration is deferred; all columns are named to map 1:1 onto future tables.
**LLM provider:** OpenRouter, free-model tier, with a one-time $10 credit purchase (see §6).

---

## 0. Conventions

- **(locked)** decided — do not change without a stated reason
- **(design)** recommended default — overrulable
- **[CONFIRM]** fact to establish before relying on it
- **(VERIFY)** recommendation to validate against live APIs before building on it

### 0.1 Canonical names

- Google Sheet tabs are exactly: `Evidence`, `Signals`, `Clusters`, `RunLog`.
- `entity_key` is the source-native entity key used for supersession and clustering. Examples: `sec:0000320193`, `edinet:E02144`, `companies_house:01234567`, `mca:U12345DL...`.
- Source-specific ids such as CIK, EDINET code, JCN, CIN, and Companies House number live in `company_ids`.
- `candidate_score` is pre-LLM. `final_score` is post-LLM.
- Local secrets live in `SHEET7SECRETS`; `.env` is tolerated for tooling, but not the project convention.

---

## 1. Architecture in one screen

```
SOURCE CONNECTORS (deterministic)
  SEC EDGAR / LDA lobbying / EDINET / Companies House / India MCA
        │  fetch documents
        ▼
  RAW CACHE (local disk, off-Sheet)        ← full source docs, git-ignored
        │  parse + section-extract
        ▼
  SECTION-AWARE TEXT                        ← 10-K: Items 1,1A,7 only; 8-K: full
        │  keyword + embedding prefilter, accumulated PER FILING
        ▼
  EVIDENCE CANDIDATES  ──────────────────►  Evidence tab (append-only)
   (ONE row per company-filing, all              one row = one company's one filing,
    matched sections stitched together)          evidence_text stitched across sections
        │  Layer A: local candidate scorer
        ▼
  candidate_score per row                   ← deterministic, no LLM
        │
        │  ── twice daily, separate workflow ──
        ▼
  SELECT top candidates by candidate_score
        │  batch into groups of 10
        ▼
  LAYER B: OpenRouter IntentSignal call     ← the ONLY LLM step
        │  returns intent_type, intent_tense,
        │  is_foreign_entering_india, evidence, confidence
        ▼
  final_score + classifier_status
        │  supersede older signal for same (entity_key, intent_type)
        ▼
  Signals tab (promoted / needs_research)   ← current reviewed signals
        │  group by company/thesis (one cluster per entity_key)
        ▼
  Clusters tab                              ← per-company audit trail across filings
```

**Two judgment layers, never confused:**
- **Layer A (deterministic, every candidate):** ranks. Cannot judge tense or foreign-entry.
- **Layer B (one batched LLM call, top candidates only):** judges intent, tense, foreign-entry. Produces the final call.

The LLM never fetches, parses, scrapes, or creates evidence. It receives compact candidate objects and returns structured judgments. Ingestion is 100% deterministic.

---

## 2. Google Sheets schema (`TAGTRIAL7`, four tabs)

No country or sector tabs in v1 — use `country_system` and `sector` columns for filtering.

### 2.1 `Evidence` (append-only — ONE ROW PER COMPANY-FILING)
**(locked) Granularity: one Evidence row = one company's one filing**, not one keyword hit. All matched windows across the strategic sections of a single filing are stitched into one `evidence_text` and judged together. See §2.5 for why and §3 for the scraper consequence.

Pre-LLM fields only. Makes it obvious which rows are merely deterministically ranked.
```
event_id              unique id for this COMPANY-FILING (e.g. sec_0000320193_10k_2026)
run_id                which connector run produced it
retrieved_at          ISO timestamp of fetch
filing_date           ISO date of the source document
source                sec | lda | edinet | companies_house | mca
country_system        US | JP | UK | IN | EU ...
disclosure_layer      filing | lobbying | ip | policy
company_name          best-effort resolved name
entity_key            source-native key, e.g. sec:0000320193 or edinet:E02144
company_ids           other ids (cik, registration, LEI), pipe-separated
sector                energy | defense | tech | pharma ...
document_type         10-K | 10-Q | 8-K | 20-F | 6-K | LDA | ...
source_url            canonical link to the filing
evidence_text         STITCHED matched windows across sections, each prefixed with
                      its section tag, e.g. "[Item 1A] ... [Item 7] ..." (see §6.6)
sections_hit          which sections contributed, pipe-separated (Item 1|Item 1A|Item 7)
matched_terms         union of keyword hits across all sections, pipe-separated
signal_label          coarse label from Layer A (india_investment, china_plus_one, ...)
candidate_score       0-100 deterministic rank (see §5)
candidate_label       Layer A's guessed category
candidate_reason      short string: why Layer A ranked it here
likely_noise          TRUE | FALSE
llm_review_status     pending | sent | reviewed | skipped
decay_weight          recency-adjusted multiplier (see §5.3)
human_review_status   unreviewed | confirmed | rejected
notes
```

### 2.2 `Signals` (promoted + needs_research — post-LLM)
Carries the intent fields Layer B produced.
```
signal_id
event_id              FK back to the Evidence row (one company-filing)
entity_key            source-native key — used to supersede older signals for same company
company_name
country_system
sector
source
document_type
filing_date
signal_label
intent_type           market_entry | expansion | diversification |
                      supply_chain_shift | regulatory_positioning |
                      ip_market_entry | none
intent_tense          stated_future | in_progress | completed |
                      speculated_by_third_party | unclear | none
is_foreign_entering_india  TRUE | FALSE
intent_evidence       the exact grounding sentence the model quoted
intent_confidence     0.0-1.0 from Layer B
final_score           0-100 post-LLM (see §5.2)
classifier_status     promoted | needs_research | rejected_noise
supersession_status   current | superseded   (see §2.5)
superseded_by         signal_id of the newer signal for this entity_key, if any
promotion_reason      short string
judgment_agreement    agree | disagree   (Layer A vs Layer B; computed post-LLM)
signal_summary        one line
why_it_matters        one line BD relevance
suggested_bd_angle    optional, from Layer B bonus field
bd_context            optional
why_now               optional
enriched_at           ISO timestamp of the Layer B call
enrichment_model      model id used
source_url
decay_weight
human_review_status   unreviewed | confirmed | rejected
notes
```

### 2.3 `Clusters` (grouped company/thesis opportunities)
```
cluster_id
company_name
country_system
sector
cluster_theme
cluster_summary
evidence_event_ids    pipe-separated
signal_ids            pipe-separated
signal_count
best_signal_id
latest_filing_date
cluster_score
human_review_status
notes
```

### 2.4 `RunLog`
```
run_id
started_at
finished_at
connector
status                ok | partial | failed
rows_seen
evidence_added
signals_added
llm_calls_made
error
```

**(design)** The Sheets writer must create/update headers and append rows **without overwriting human-edited columns** (`human_review_status`, `notes`). Append and upsert by id; never blind-overwrite a row.

### 2.5 Deduplication and supersession (REQUIRED by filing-level granularity)

**Why this exists:** because one Evidence row is now one company-filing, the same company recurs every time a new filing mentions India — a 10-K this year, a 10-Q next quarter, an 8-K next week. Without a rule, the Signals tab fills with near-duplicate rows for one company, and a consultant can't tell which is the live read.

**The entity key is `entity_key`**. For SEC this is `sec:<CIK>`; for non-SEC sources it is the native registry id with a source prefix. All filings from the same `entity_key` describe the same company's evolving intent.

**Supersession rule (locked):**
```
When a new Signal is promoted for an entity_key that already has a current Signal:
  - The NEW signal (later filing_date) becomes supersession_status = current.
  - The OLD signal is set supersession_status = superseded,
    superseded_by = new signal_id.
  - The old signal is NOT deleted — it stays for history/audit, but is
    filtered out of the default "live prospects" dashboard view.
Tie-break: if two filings share a date, the higher document authority wins
  (10-K > 20-F > 8-K > 10-Q), then higher final_score.
```

**Clusters is where a company's signals aggregate (locked):** one cluster per `entity_key` (or per company-thesis). The cluster holds every signal_id for that company across filings, points `best_signal_id` at the current highest-scoring one, and tracks `latest_filing_date`. The dashboard reads **current** signals; the cluster is the audit trail of how that company's intent evolved. This is the answer to "we keep seeing the same company" — they collapse into one cluster, not N duplicate rows.

**A company can legitimately hold two DIFFERENT live intents** (e.g. `regulatory_positioning` via lobbying AND `expansion` via a 10-K). Supersession is scoped to `(entity_key, intent_type)`, not `entity_key` alone — a new expansion signal supersedes the old expansion signal, but does not touch the lobbying signal.

---

## 3. Keyword prefilter (high-recall gate only)

Keywords decide **what enters `Evidence`**, nothing more. They never decide intent. Wide net, false positives expected and acceptable — Layer A ranks them down and Layer B filters them out.

```
India:        India, Indian, Bharat, South Asia, Indo-Pacific, インド, 南アジア
China+1:      China+1, China plus one, supply chain diversification,
              supply-chain resilience, derisking, de-risking, friendshoring,
              nearshoring, reshoring, relocation, manufacturing shift,
              production transfer, supplier concentration, alternative
              geographies, non-China sourcing
Action:       invest, investment, capex, capital expenditure, expand,
              expansion, new facility, plant, factory, manufacturing,
              production base, subsidiary, branch, office, regional hub,
              acquisition, joint venture, MoU, restructuring, evaluating,
              planning, entering, launching
Policy:       USTR, tariff, customs, market access, trade, export controls,
              sanctions, FDI, data localization, digital trade, AI, telecom,
              pharma, medical devices, defence, defense, semiconductors,
              energy, infrastructure, tax treaty
IP:           patent, patent application, PCT, national phase,
              India national phase, publication, grant, applicant, assignee,
              owner, trademark, Madrid, intellectual property, IP filing
Japanese:     インド, 生産拠点, 工場, 製造, 設備投資, 子会社, 買収,
              供給網, サプライチェーン, 中国
```

**(design)** Optionally augment keyword recall with an embedding-similarity prefilter against a small set of prototype "intent" sentences, so paraphrased intent that dodges the keyword list still enters `Evidence`. This is the cheap local embedding step, no LLM.

**(locked) Scraper accumulation — one Evidence row per filing, not per hit.** Because granularity is filing-level (§2.1, §2.5), the prefilter does NOT write a row each time a keyword matches. Per filing it:
```
1. Extract the strategic sections (§7): Item 1, Item 1A, Item 7 for a 10-K.
2. Scan each section for keyword/embedding hits, capturing a window around each hit.
3. If the filing has >=1 hit across any section:
     - stitch the windows into one evidence_text, each prefixed by its section tag
     - union the matched_terms across sections
     - record sections_hit
     - write ONE Evidence row with event_id = sec_<cik>_<doctype>_<year> and entity_key = sec:<cik>
4. If zero hits in any strategic section: raw_cache only, no Evidence row.
```
A filing that mentions India in Risk Factors AND in MD&A produces one row whose evidence_text carries both, so Layer B sees the corroborated picture (this is the split-intent fix).

---

## 4. Classifier status logic (the final decision)

`classifier_status` is the combination of Layer A and Layer B. Never keywords alone.

```
promoted:
    Layer A: candidate relevant (candidate_score cleared the send threshold)
    AND Layer B: intent_type != none
    AND intent_tense in (stated_future, in_progress)
    AND is_foreign_entering_india = TRUE
        UNLESS disclosure_layer in (lobbying, ip)
        OR signal_label = china_plus_one competitor-market logic
        (these are valuable even for domestic/competitor entities)
    AND intent_confidence >= 0.70   [CONFIRM threshold after first runs]

needs_research:
    Layer A: relevant
    BUT  intent_confidence < 0.70
    OR   intent_tense = unclear
    OR   judgment_agreement = disagree
    OR   strategically interesting but evidence not clean enough

rejected_noise:
    Layer B: intent_type = none
    OR  intent_tense = completed  (and no current BD angle)
    OR  intent_tense = speculated_by_third_party
    OR  is_foreign_entering_india = FALSE and not covered by the lobbying/ip/china+1 exception
    OR  generic country-list / boilerplate
```

**Disagreement is defined explicitly:**
- Layer A says relevant, Layer B says none/unclear/completed/speculation → `needs_research`.
- Layer A flagged `likely_noise=TRUE`, but Layer B finds live intent → `needs_research` (NOT auto-promote — surface for a human, don't trust the override blindly).

**(design) Deterministic-only promotion exception** (so the system stays useful if OpenRouter is unreachable):
```
IF candidate_score >= 90
   AND source in (sec, lda)               (official source)
   AND evidence_text directly states future/in-progress India
       investment, lobbying, or market entry
THEN write to Signals as classifier_status = needs_research,
     promotion_reason = "deterministic_provisional",
     human_review_status = unreviewed
```

---

## 5. Scoring (pre-LLM and post-LLM are separate numbers)

### 5.1 `candidate_score` — pre-LLM, decides what gets sent to Layer B
```
source_reliability        0-25   (official filing > lobbying > IP > press)
company_resolved          0-15   (clean entity match > fuzzy > none)
india_or_china1_relevance 0-20   (strength/density of India/China+1 hits,
                                  scored over the full stitched evidence_text)
action_intent_strength    0-25   (action verbs near the entity, future-leaning)
recency                   0-10   (newer filings score higher)
local_classifier_signal   0-5    (Layer A's own confidence)
                          ─────
                          0-100

(design) Cross-section corroboration bonus: fold into action_intent_strength —
a filing with hits in MULTIPLE strategic sections (e.g. concentration risk in
Item 1A AND a geography plan in Item 7) scores higher than a single isolated
mention. Multi-section intent is harder to fake and is the strongest pre-LLM
signal. Use sections_hit count to award this.
```

### 5.2 `final_score` — post-LLM, decides promotion
```
start from candidate_score, then:
  + up to 20   live stated_future / in_progress intent
  + up to 10   high Layer B confidence (>= 0.85)
  + up to 5    exact grounded evidence sentence present
  - up to 25   intent_tense = completed
  - up to 30   intent_tense = speculated_by_third_party
  - up to 30   is_foreign_entering_india = FALSE (domestic false positive)
  - up to 15   weak / unclear evidence
clamp to 0-100
```

### 5.3 `decay_weight` — intent goes stale
```
decay_weight = exp(-age_days / HALF_LIFE_DAYS)
HALF_LIFE_DAYS default 180   [CONFIRM after observing real signal turnover]
```
Apply `decay_weight` as a multiplier on `final_score` when ranking the Signals tab, so an entry-intent from an 18-month-old 10-K doesn't rank as a live prospect. **This is mandatory for a derived (auto-generated) watchlist — without it the tab fills with stale intent.**

---

## 6. OpenRouter — budget, caps, and exact mechanics (locked)

### 6.1 The budget decision
- Free tier without credits: **50 free-model requests/day**, 20 requests/minute.
- OpenRouter FAQ says purchasing at least $10 in credits raises the free-model daily limit to **1000 requests/day**. The 20 RPM ceiling is unchanged. Credits are still governed by OpenRouter billing terms, so do not describe them as permanent.
- Keep local caps configurable even after buying credits: `OPENROUTER_AUTO_DAILY_CAP`, `OPENROUTER_BATCH_SIZE`, and `OPENROUTER_MODEL`.
- **(locked) Use OpenRouter only for Layer B intent judgment.** It does not ingest, parse, or discover.
- **Failed requests still count against the daily quota.** Build retries with backoff; do not hammer on 429.

### 6.2 The 20 RPM ceiling still governs burst behavior
Even with 1000/day, you may send at most 20 requests/minute. Batching (below) keeps you far under this. If you ever loop many calls, space them ~3 seconds apart.

### 6.3 Why batched, not one-by-one
One OpenRouter call can carry many candidates in a single prompt and return one judgment per candidate. Reviewing 20 candidates one-per-call costs 20 requests; batched at 10 per call it costs 2. Batching is strictly better: fewer requests, less 429 exposure, identical per-candidate quality (each candidate is judged on its own evidence sentence; they do not interact). **Stay batched even though the $10 upgrade makes one-by-one affordable.**

### 6.4 Batch size
**(design)** Default **10 candidates per call**. Drop to 5 if you observe per-candidate quality slipping with larger batches. Raise toward 15 only if evidence snippets are short.

### 6.5 The twice-daily workflow
A **separate** workflow from ingestion, on a schedule:

```
Run at two times per day.
(design) Set the times to ~1 hour after each major source's publication window,
         NOT round clock numbers.
(VERIFY) Confirm SEC EDGAR's daily dissemination window (filings concentrate
         after US market close, Eastern). Put run 1 shortly after that window.
         Run 2 catches stragglers + non-US sources (EDINET = Tokyo time).

Per run:
  1. Read all Evidence rows where llm_review_status = pending.
  2. Sort by (candidate_score desc, filing_date desc).
  3. Take the top N for this run.
        (design) N defaults to OPENROUTER_AUTO_DAILY_CAP / number_of_runs, while
        validating quality. Keep this small until the first live runs prove value.
  4. Split N into batches of 10.
  5. For each batch, make ONE OpenRouter call (§6.6), spacing calls >=3s apart.
  6. Parse each returned IntentSignal; for each:
       - set intent_* fields on the Evidence/Signals row
       - compute final_score (§5.2) and classifier_status (§4)
       - set llm_review_status = reviewed
       - write promoted / needs_research rows to the Signals tab
  7. Log to RunLog: rows_seen, evidence_added, signals_added, llm_calls_made.
  8. Idempotency guard: never re-send a row already marked reviewed unless --force.
```

### 6.6 What a call actually looks like

**Model choice (design):** use a free model that supports `response_format: json_schema`. Set `require_parameters: true` so OpenRouter only routes to providers that honor the schema — otherwise a provider may silently ignore it and return prose your parser can't read. (VERIFY the current free-model roster for structured-output support at build time; the roster rotates. Candidates as of mid-2026 include the larger free Qwen / DeepSeek / Llama variants.)

**Request (Python, OpenAI-compatible client):**
```python
import os, json, time
from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

# The JSON Schema for ONE candidate's judgment.
INTENT_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "event_id": {"type": "string"},
        "entity": {"type": "string"},
        "is_foreign_entering_india": {"type": "boolean"},
        "intent_type": {"type": "string", "enum": [
            "market_entry","expansion","diversification","supply_chain_shift",
            "regulatory_positioning","ip_market_entry","none"]},
        "intent_tense": {"type": "string", "enum": [
            "stated_future","in_progress","completed",
            "speculated_by_third_party","unclear","none"]},
        "intent_evidence": {"type": "string"},
        "confidence": {"type": "number"},
        "short_reason": {"type": "string"},
        "optional_bd_angle": {"type": ["string","null"]},
    },
    "required": ["event_id","entity","is_foreign_entering_india","intent_type",
                 "intent_tense","intent_evidence","confidence","short_reason"],
    "additionalProperties": False,
}

# We ask for a batch: an object with a "results" array, one item per candidate.
BATCH_SCHEMA = {
    "name": "intent_batch",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "results": {"type": "array", "items": INTENT_ITEM_SCHEMA}
        },
        "required": ["results"],
        "additionalProperties": False,
    },
}

SYSTEM = (
    "You judge whether each disclosure shows a FOREIGN company forming intent "
    "to enter, expand in, or shift supply chains toward INDIA. "
    "Each candidate's evidence_text is stitched from multiple filing sections, "
    "each prefixed with a [Section] tag; weigh forward-looking sections "
    "(MD&A, Business) more heavily than boilerplate risk-factor recitals. "
    "Judge each candidate independently using ONLY its evidence_text. "
    "intent_tense is critical: stated_future or in_progress = live; "
    "completed = already happened; speculated_by_third_party = an analyst guessing, "
    "not the company. If the entity is an Indian domestic company, set "
    "is_foreign_entering_india=false. Quote the single exact grounding sentence in "
    "intent_evidence (the one that best proves the intent). "
    "Return one result object per candidate, keyed by event_id. "
    "Do not invent intent that the text does not state."
)

def review_batch(candidates: list[dict], model: str) -> list[dict]:
    """candidates: compact dicts. Returns list of IntentSignal dicts."""
    user_payload = {"candidates": candidates}
    resp = client.chat.completions.create(
        model=model,                       # a :free model that supports json_schema
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(user_payload)},
        ],
        response_format={"type": "json_schema", "json_schema": BATCH_SCHEMA},
        extra_body={"provider": {"require_parameters": True}},  # enforce schema routing
        max_tokens=2000,
        temperature=0,                      # deterministic judgments
    )
    content = resp.choices[0].message.content
    return json.loads(content)["results"]
```

**Compact candidate sent in (ONE per company-filing, section-tagged, never the full filing):**
```json
{
  "event_id": "sec_0001234567_10k_2026",
  "company_name": "Example Corp",
  "entity_key": "sec:0001234567",
  "company_ids": "cik:0001234567",
  "country_system": "US",
  "source": "sec",
  "document_type": "10-K",
  "filing_date": "2026-02-20",
  "sections_hit": ["Item 1A", "Item 7"],
  "evidence_text": "[Item 1A Risk Factors] We face supply-chain concentration risk in a single geography and may be unable to mitigate disruption. [Item 7 MD&A] We are evaluating additional manufacturing capacity in India to diversify sourcing away from that geography.",
  "matched_terms": ["India", "manufacturing capacity", "diversify", "concentration"]
}
```

**One result object returned per candidate:**
```json
{
  "event_id": "sec_0001234567_10k_2026",
  "entity": "Example Corp",
  "is_foreign_entering_india": true,
  "intent_type": "supply_chain_shift",
  "intent_tense": "stated_future",
  "intent_evidence": "We are evaluating additional manufacturing capacity in India to diversify sourcing away from that geography.",
  "confidence": 0.86,
  "short_reason": "Company states future evaluation of India manufacturing to diversify supply.",
  "optional_bd_angle": "India site-selection and manufacturing-entry advisory."
}
```

### 6.7 Failure handling
```
- response_format unsupported by routed provider → request fails; log, fall back
  to a different free model in a configured chain, then to the §4 deterministic
  exception if all fail.
- malformed / non-parseable JSON → log to RunLog.error, do NOT corrupt existing
  rows, mark those candidates llm_review_status = pending for next run.
- 429 → exponential backoff; remember failed calls still consume daily quota.
- partial batch (model returns fewer results than candidates) → match by event_id,
  re-queue the missing ones as pending.
```

---

## 7. Document ingestion — section-aware (VERIFY)

Anchor on filing **section**, not keyword position.
```
10-K / 20-F : extract Item 1 (Business), Item 1A (Risk Factors), Item 7 (MD&A).
              Skip financial statements and footnotes.
8-K / 6-K   : short filings — scan in full.
LDA         : full disclosure text (short).
Transcripts : Q&A section.
```
- Use the SEC API / archive as source of truth.
- A HuggingFace S&P 500 10-K dataset may be used as **offline eval data only**, never as a live source.
- **(VERIFY)** the exact EDGAR endpoint + Item parser before writing the scraper. This is the one load-bearing unverified piece; confirm which parser cleanly splits a 10-K into Items.

---

## 8. Source scope and priority

```
1. SEC EDGAR    10-K, 10-Q, 8-K, 20-F, 6-K     (US filings — primary)
2. US LDA       lobbying disclosures
3. EDINET       Japan filings
4. Companies House  UK
5. India MCA / data.gov.in
6. IP (EPO / Lens / USPTO)                       later
7. EU / Canada / other APAC                       after US + Japan flow works
```

---

## 9. Secrets

```
Local secrets file (git-ignored):  SHEET7SECRETS
Present:  DATA_GOV_IN_API_KEY, EDINET_API_KEY,
          GOOGLE_SHEETS_SPREADSHEET_ID, GOOGLE_SERVICE_ACCOUNT_JSON
Needed when used: SEC_USER_AGENT, LDA_API_KEY, COMPANIES_HOUSE_API_KEY,
          OPENROUTER_API_KEY, OPENROUTER_MODEL (default a :free schema-capable model)
SHEET7SECRETS, .env, secrets/ stay git-ignored.
```

---

## 10. Tests

```
- Prefilter: a strong SEC India-expansion sentence enters Evidence;
  a generic "operations in India, China, and Brazil" country list does not promote.
- Granularity: a filing with India hits in Item 1A AND Item 7 produces ONE Evidence
  row whose evidence_text contains both, tagged by section (not two rows).
- A filing with zero strategic-section hits → raw_cache only, no Evidence row.
- Cross-section corroboration raises candidate_score above a single-section mention.
- candidate_score and final_score are stored as SEPARATE columns.
- Batch call: 10 candidates in → 10 results out, matched by event_id.
- Layer A relevant + Layer B intent_type=none → needs_research (not promoted).
- Layer A likely_noise=TRUE + Layer B live intent → needs_research (not promoted).
- intent_tense completed and speculated_by_third_party → not promoted.
- is_foreign_entering_india=FALSE → not promoted, except lobbying/ip/china+1 path.
- Supersession: a newer 10-K for an existing entity_key sets the old signal
  supersession_status=superseded, superseded_by=new id; old row retained, hidden
  from the live view.
- Supersession is scoped to (entity_key, intent_type): a new expansion signal does NOT
  supersede that company's separate live lobbying signal.
- Supersession tie-break: same filing_date, 10-K beats 10-Q.
- Clusters: N filings for one company collapse into one cluster, best_signal_id
  points at the current highest-scoring signal.
- response_format unsupported → falls back through model chain, then deterministic exception.
- malformed LLM JSON → logged, existing rows intact, candidates re-queued pending.
- 429 → backoff; quota-aware (failed calls counted).
- decay_weight reduces ranking of an old-but-high final_score row.
- Sheets writer never overwrites human_review_status or notes.
- Idempotency: a reviewed row is not re-sent without --force.
- Daily limit guard: workflow respects the 1000/day cap and 20 RPM ceiling.
```

---

## 11. Open items

| # | Item | Status |
|---|---|---|
| 1 | EDGAR section-extraction endpoint + Item parser | **(VERIFY) §7** |
| 2 | Current free models on OpenRouter supporting json_schema | (VERIFY) §6.6 — roster rotates |
| 3 | `intent_confidence` promotion threshold (default 0.70) | [CONFIRM] §4 after first runs |
| 4 | `decay_weight` half-life (default 180 days) | [CONFIRM] §5.3 after observing turnover |
| 5 | Exact twice-daily run times tied to source publication windows | (VERIFY) §6.5 |
| 6 | Per-run candidate cap N (default 50) | (design) §6.5 |
| 7 | Entity resolution across sources: SEC CIK is clean, but EDINET/Companies House/MCA use different ids. A foreign parent and its India subsidiary may have separate ids — supersession by source-native `entity_key` won't link them. Need a cross-source entity map before non-SEC sources go live. | [CONFIRM] §2.5 |
