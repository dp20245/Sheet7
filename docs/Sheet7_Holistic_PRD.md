# Sheet7 — Public Disclosures Intent Engine — Holistic PRD

**Owner:** Darsh Puri
**Parent system:** TAG Cross-Border BD Intelligence (Phase 4 PRD)
**This component:** Sheet7 — the public-disclosures intent engine. The highest-value feed in the parent system.
**Companion document:** `Sheet7_Build_Spec.md` holds the column-level schema, scoring tables, and full OpenRouter code. This PRD is the holistic layer: what Sheet7 is, why it exists, how its stages fit, the Phase 0 source probe, and the build sequence. Where this PRD says "see Build Spec §X," the detail lives there. The two are meant to be read together.

---

## 0. Conventions

- **(locked)** decided — do not change without a stated reason
- **(design)** recommended default — overrulable
- **[CONFIRM]** a fact to establish before relying on it
- **(VERIFY)** a recommendation to validate against live APIs before building on it
- **(verified)** checked against live docs/APIs as of June 2026; cited

---

## 1. Where Sheet7 sits in the parent system

The TAG system is **one engine, three surfaces** (dashboard, newsletter, chatbot) over a shared store. The engine's core operation is joining a *signal* against an *entity's derived intent* to produce a named BD prospect. Intent is not human-curated and does not come from TAG's relationships; it is **derived from public documents**. That decision is what makes the system automatable, and it is what makes Sheet7 central.

**Sheet7 is the intent engine's primary source.** Of the parent system's six live sheets, Sheet7 (disclosures: filings, lobbying, IP) and Sheet4 (jobs) are the two that *generate intent* rather than context. The other sheets (news, VC, OSINT) describe what happened; Sheet7 reveals what a company *intends*. When Sheet7 extracts "this foreign firm states future India manufacturing intent," that row becomes an entry in the system's derived watchlist, which every downstream inference joins against.

```
Sheet7 output  ─────►  intents (derived watchlist)  ─────►  inference engine
(this document)         entity + intent_type +              joins intent × signals
                        tense + evidence + decay            → ranked prospects
                                                            → dashboard / newsletter
```

So Sheet7's quality ceiling is the system's quality ceiling. A weak intent extractor here produces a watchlist of false positives that no amount of downstream cleverness repairs.

---

## 2. What Sheet7 does, in one paragraph

Source connectors deterministically fetch public filings, lobbying records, and IP disclosures. A keyword/embedding prefilter, accumulated per filing, writes one Evidence row per company-filing with intent-bearing text stitched across the filing's strategic sections. A cheap local layer (Layer A) ranks every candidate. Twice a day, a separate workflow sends the top-ranked candidates — batched, ten per call — to a single LLM step (Layer B) that judges intent type, tense, and foreign-entry status against a strict schema. Promoted signals land in a reviewed-signals tab, deduplicated so each company's latest intent supersedes its older one. No LLM touches ingestion; the LLM only judges.

Full mechanics: Build Spec §1–§9.

---

## 3. The four principles that govern every design choice (locked)

These are the load-bearing decisions. Everything else follows.

**3.1 Keywords prefilter; they never classify.** A keyword match decides only what enters Evidence. It cannot tell "intends to enter" from "completed entry" from "analyst speculates entry," nor foreign-entrant from domestic. Treating keywords as the classifier is the original sin this whole design avoids. Build Spec §3.

**3.2 Two judgment layers, never merged.** Layer A (local, deterministic, every candidate) *ranks*. Layer B (one batched LLM call, top candidates only) *judges intent and tense*. Final status combines both. Layer A may guess a label; it may never make the tense or foreign-entry call. Build Spec §1, §2.5, §4.

**3.3 The LLM does the hard job, not the easy one.** The expensive reasoning is judging intent and tense from hedged filing language. Writing BD prose is nearly templatable. The LLM is spent on intent extraction; the BD angle is a bonus field on the same call, never the purpose. Build Spec §3 (vocabulary), §6.6.

**3.4 Intent is derived and decays.** Because the watchlist is auto-generated from filings, not curated by a human, it has no natural freshness. An entry intent from a 2024 10-K is not a live 2026 prospect. Every intent carries a source date and a decay weight; stale intent is filtered from the live view. Build Spec §5.3.

---

## 4. Granularity: one row per company-filing (locked)

The unit of an Evidence row is **one company's one filing**, not one keyword hit. All matched windows across a filing's strategic sections are stitched into one `evidence_text`, section-tagged, and judged together.

**Why:** intent in a 10-K is split across sections — concentration risk stated in Item 1A, the geography plan in Item 7. A per-hit unit fragments this and the LLM judges half the picture. A per-filing unit lets the LLM see the corroborated whole. Build Spec §2.1, §3 (scraper accumulation).

**The consequence this forces — supersession.** One row per filing means a company recurs every quarter it files, so without a rule the reviewed-signals tab fills with near-duplicates. The rule: a newer filing's signal supersedes the older one for the same `(entity, intent_type)`; the old row is retained for audit but hidden from the live view; companies collapse into one cluster tracking how their intent evolved. Build Spec §2.5.

---

## 5. The multi-source reality (corrected — this build is NOT US-only)

An earlier draft implied a US-only first build. That was an unstated assumption, now corrected. The build is multi-source from the start. But the sources are **not equivalent**, and pretending they are would waste connector effort. Research and the Phase 0 probe (§6) establish what each actually provides:

| Source | Entity key | What it returns | Intent-bearing? | Role |
|---|---|---|---|---|
| **SEC EDGAR** | CIK (clean, stable) | 10-K/20-F narrative: Item 1, 1A, 7 | **Yes — rich prose** | Primary intent source |
| **US LDA** | client name (no stable id) | lobbying issue descriptions | **Yes — terse intent** (regulatory_positioning) | Primary intent source |
| **EDINET (JP)** | edinetCode + JCN (stable) | XBRL ZIP; narrative only in JP text-blocks | **Limited** — needs unzip + JA→EN | Secondary; highest processing cost |
| **Companies House (UK)** | company_number (stable) | filing metadata; financial accounts | **Weak** — thin narrative | Mostly entity resolution |
| **India MCA / data.gov.in** | CIN (stable) | master data; docs behind paid fee | **None in free tier** | India entity-resolution spine |

**The strategic read (likely, pending probe confirmation):** EDGAR and LDA are the real intent engines. EDINET is intent-bearing but expensive. Companies House and MCA are primarily *entity-resolution infrastructure* — they tell you who and where a company is, not what it intends. MCA specifically is how you link a foreign parent's SEC CIK to its Indian subsidiary's CIN. Build the rich sources first; bring the others in as resolution support.

**The cross-source entity problem (day-one concern, not a future cliff).** Supersession and clustering key on the entity. EDGAR's CIK is clean within EDGAR. Across sources the ids differ, and a foreign parent and its India subsidiary carry *different* ids. Without a cross-source entity map, "Example Corp (SEC)" and "Example India Pvt Ltd (MCA)" fragment into separate companies. This is why MCA's value is resolution, not intent. Build Spec open item 7.

---

## 6. Phase 0 — the source probe (run BEFORE building any connector)

**Script:** `sheet7_source_probe.py`. **Purpose:** not "does the API work" but "what does each source actually return, so we build the right connector instead of assuming." It answers three questions per source and writes raw samples for inspection.

**The three questions per source:**
1. **Entity key** — what does the company identifier look like? (feeds the cross-source entity map)
2. **Structure** — parseable sections, flat blob, XBRL numbers, or just metadata?
3. **Intent text** — is there narrative prose where intent could be expressed, or only numbers and compliance fields?

**What it does, per source:** resolves a company, pulls a small sample, dumps the raw shape to `./probe_out/`, prints a VERDICT block answering the three questions. It writes nothing to Sheets and calls no LLM. Missing API keys are reported and skipped, not fatal.

**Sources probed:** SEC EDGAR (baseline/control), US LDA, EDINET, Companies House, India MCA.

**How to run:**
```
pip install requests
# set whatever keys you have in SHEET7SECRETS:
#   SEC_USER_AGENT (required by SEC or you get 403), LDA_API_KEY, EDINET_API_KEY,
#   COMPANIES_HOUSE_API_KEY, DATA_GOV_IN_API_KEY (+ DATA_GOV_IN_MCA_RESOURCE)
python sheet7_source_probe.py            # all sources
python sheet7_source_probe.py --only edinet
python sheet7_source_probe.py --company "Hitachi"
```

**The output is a decision input, not a deliverable.** Darsh runs it, pastes the VERDICT blocks and a sample file or two back, and each connector is finalised against the *real* response shape rather than this PRD's assumptions. Specifically, the probe confirms or breaks: whether EDINET narrative is extractable without prohibitive effort, whether Companies House has any forward-looking section worth reading, and what the current data.gov.in MCA resource id and field set are.

**(open) MCA resource id:** data.gov.in resource ids rotate; the probe takes the current one as an env var rather than hardcoding a stale one. Darsh must supply a current company-master resource id, or the India entity spine routes through the MCA Company Master via a different access path. [CONFIRM]

---

## 7. Document ingestion — the verified EDGAR path (verified)

Anchor extraction on filing **section**, not keyword position.
```
10-K / 20-F : Item 1 (Business), Item 1A (Risk Factors), Item 7 (MD&A). Skip financials/footnotes.
8-K / 6-K   : short filings — full scan.
LDA         : full disclosure text (short).
```

**(verified, June 2026) The free section-extraction path is the open-source `sec-edgar-toolkit`.** `filing.extract_items()` returns a dict keyed by Item — `{"1":..., "1A":..., "7":...}` — and a 10-K parses in roughly a quarter-second. Do **not** hand-roll a regex splitter: "Item 1" matches inside "Item 11" and "Item 12," so naive parsers grab the wrong boundary and return None. The maintained library already disambiguates Item boundaries. A paid alternative (`sec-api.io` Extractor API, `get_section(url, "1A", "text")`) exists but is unnecessary given the free toolkit.

**(verified) SEC requires a `User-Agent` header** identifying app and email, or it returns 403. This is the `SEC_USER_AGENT` secret. With it set, EDGAR is fully free.

This moves the parent system's long-standing (VERIFY) on EDGAR to settled.

EDINET note (from research, pending probe): EDINET API v2 returns a ZIP of XBRL CSVs (UTF-16, tab-delimited); narrative lives in XBRL text-block elements in Japanese. The `edinet-tools` library exposes `report.text_blocks`. Plan for unzip → extract narrative blocks → JA→EN before the LLM. Build Spec §7, §11.

---

## 8. The LLM layer — budget, batching, and call shape

**Budget (verified, June 2026):** OpenRouter free tier is 50 free-model requests/day; purchasing at least $10 in credits raises this to 1000/day. The 20-requests-per-minute ceiling persists regardless. Credits remain subject to OpenRouter billing terms, so the implementation uses explicit caps (`OPENROUTER_AUTO_DAILY_CAP`, `OPENROUTER_BATCH_SIZE`) instead of assuming unlimited use. Note: failed requests still consume quota, so retries use backoff.

**Batching (locked):** one call carries up to 10 candidates and returns one judgment per candidate, keyed by `event_id`, in a single JSON object — `{"results": [ {...}, {...} ]}`. Reviewing 20 candidates costs 2 calls batched, not 20. Per-candidate quality is identical because each is judged on its own evidence text; they share a prompt, not a judgment. Stay batched even though the $10 makes one-by-one affordable. Build Spec §6.3–§6.4.

**Schema enforcement (verified):** the call uses OpenRouter's `response_format: {type: "json_schema"}` with `require_parameters: true` in provider preferences, so OpenRouter only routes to providers that honor the schema — otherwise a provider may silently return prose the parser can't read. Build Spec §6.6 has the runnable Python, the `IntentSignal` schema, and the exact request/response examples.

**Cadence (design, VERIFY times):** twice daily, on a separate workflow from ingestion, with run times tied to **source publication windows** — EDGAR filings concentrate after US market close (Eastern); EDINET is Tokyo time — not round clock numbers. Verify EDGAR's dissemination window and set run 1 shortly after it; run 2 catches stragglers and non-US sources. Build Spec §6.5.

---

## 9. Promotion and the human boundary

`classifier_status` is the combined Layer A + Layer B verdict. Build Spec §4 has the full logic. The shape:
- **promoted:** Layer A relevant AND Layer B finds live intent (tense ∈ stated_future/in_progress) AND foreign-entering-India (unless lobbying/IP/China+1, where it counts regardless) AND confidence clears threshold.
- **needs_research:** relevant but low confidence, unclear tense, or Layer A and Layer B disagree.
- **rejected_noise:** intent_type none, completed-with-no-angle, third-party speculation, or domestic false positive.

**(locked) Naming honesty:** the reviewed-signals tab is `Signals`, not "verified leads." What lands there is *model-judged*, not verified. A `human_review_status` column tracks actual human verification. Calling it "verified" would make a TAG consultant trust an unverified machine judgment, and the first wrong one damages the tool. The machine never marks a lead human-verified.

---

## 10. Build sequence

```
Phase 0  Run sheet7_source_probe.py. Paste verdicts back. Finalise connector
         designs against real response shapes. Resolve MCA resource id.        ← DO FIRST

Phase 1  Foundation. Create TAGTRIAL7 four-tab schema (Build Spec §2).
         Sheets writer that upserts by id and never overwrites human columns.
         Secrets wiring. Deterministic scoring module (Build Spec §5.1).

Phase 2  EDGAR connector (the rich, verified source). sec-edgar-toolkit section
         extraction → per-filing Evidence rows with stitched section text →
         candidate_score. Prove the deterministic pipeline end to end on real 10-Ks.

Phase 3  LDA connector (second intent source, structured, easy). Lobbying issue
         descriptions → Evidence with disclosure_layer=lobbying.

Phase 4  Layer B. Buy the $10 OpenRouter credit. Wire the batched IntentSignal
         call (Build Spec §6.6). Twice-daily workflow. Promotion + supersession.
         Now the engine produces real intent signals.

Phase 5  Secondary sources by probe verdict. EDINET (with JA→EN) if the probe
         shows extractable narrative. Companies House + MCA as entity-resolution
         support. Build the cross-source entity map.

Phase 6  Validate signal quality on the live Sheet. THEN decide Supabase migration
         (columns already map 1:1). Migration is a transfer, not a redesign.
```

The ordering reflects the principles: prove the deterministic spine on the richest source before adding the LLM, add the LLM before adding hard sources, and validate signal quality on Sheets before committing infrastructure.

---

## 11. Risks and open items

| # | Risk / item | Why it matters | Status |
|---|---|---|---|
| 1 | EDINET narrative may be costly to extract (XBRL + JA→EN) | Could make Japan low-ROI vs effort | Probe confirms — §6 |
| 2 | Cross-source entity resolution (parent ≠ subsidiary ids) | Fragments one company into several; breaks supersession | Day-one design — §5, Build Spec #7 |
| 3 | MCA free tier has no intent prose; docs are paid | India is resolution-only, not an intent source | (verified) — §5 |
| 4 | `intent_confidence` promotion threshold (default 0.70) | Too low = noise promoted; too high = misses | [CONFIRM] after first runs |
| 5 | `decay_weight` half-life (default 180d) | Wrong value surfaces stale or drops live intent | [CONFIRM] after observing turnover |
| 6 | Free-model roster for json_schema rotates | A chosen model may stop being free/schema-capable | (VERIFY) at build — Build Spec §6.6 |
| 7 | Twice-daily run times vs source publication windows | Wrong times batch before filings exist | (VERIFY) EDGAR window — §8 |
| 8 | data.gov.in MCA resource id rotates | Probe can't hit MCA without a current id | [CONFIRM] — §6 |

---

## 12. Definition of done (Sheet7 v1)

- Probe run, verdicts reviewed, connectors finalised against real shapes.
- EDGAR + LDA connectors producing per-filing Evidence rows with section-stitched text.
- Layer A scoring populating candidate_score deterministically.
- $10 OpenRouter credit live; twice-daily Layer B batch producing IntentSignal judgments.
- Promotion + supersession writing current, deduplicated rows to the Signals tab.
- A human can open TAGTRIAL7 and see ranked, intent-judged, decay-aware foreign-entry signals with grounding evidence and source links — and tell at a glance which are model-judged vs human-confirmed.
- Signal quality assessed on real output before any Supabase migration is scheduled.

**Companion:** `Sheet7_Build_Spec.md` for column schemas, scoring weights, classifier logic, and the full OpenRouter implementation. **Parent:** Phase 4 PRD for how Sheet7's output feeds the dashboard, newsletter, and inference engine.
