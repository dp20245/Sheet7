# Sheet7

Public-disclosures intent engine for TAG cross-border BD.

## Source Of Truth

- `docs/Sheet7_Holistic_PRD.md`: why Sheet7 exists and how the phases fit.
- `docs/Sheet7_Build_Spec.md`: exact schema, scoring, promotion, and OpenRouter contract.
- `scripts/sheet7_source_probe.py`: Phase 0 source-shape probe before connector work.

## Canonical Google Sheet Tabs

- `Evidence`: one candidate row per company filing/disclosure.
- `Signals`: promoted or needs-research intent signals.
- `Clusters`: grouped company/thesis audit trail.
- `RunLog`: connector and LLM run status.

No `Sheet7 Evidence`, `Sheet7 Signals`, sector tabs, `Classifier Audit`, or `Source Health` tabs in v1.

## Canonical Names

- `entity_key`: source-native entity key used for supersession, e.g. `sec:0000320193`, `edinet:E02144`, `companies_house:01234567`, `mca:U12345DL...`.
- `company_ids`: pipe-separated secondary ids, e.g. `cik:0000320193|lei:...`.
- `candidate_score`: deterministic pre-LLM rank.
- `final_score`: post-LLM promotion score.
- `llm_review_status`: `pending`, `sent`, `reviewed`, or `skipped`.
- `classifier_status`: `promoted`, `needs_research`, or `rejected_noise`.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example SHEET7SECRETS
pytest
```

Install optional extras only when needed:

```bash
pip install -e ".[classifiers,sheets]"
```

Run EPO OPS patent discovery after creating an app in the EPO Developer Portal
and setting `EPO_OPS_CLIENT_ID` / `EPO_OPS_CLIENT_SECRET` in `SHEET7SECRETS`:

```bash
sheet7 run-epo-ops --applicant "Acme Corp" --max-results 10 --dry-run --verbose
```

## Safety

This repo can be public. Do not commit `SHEET7SECRETS`, `.env`, raw filing caches, Google credentials, downloaded source dumps, or private review notes.
