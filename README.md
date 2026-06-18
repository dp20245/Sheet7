# Sheet7

Public-disclosures pipeline for TAG Sheet 7.

The project scans public company disclosures, lobbying/policy records, and India-relevant IP signals for evidence of India interest, China+1 movement, market-entry intent, policy friction, or competitor-market choices.

## V1 Shape

Google Sheets output is layered:

- `Sheet7 Evidence`: append-only evidence windows from all countries and all sources.
- `Sheet7 Signals`: promoted non-noise signals.
- `Energy`: sector view derived from signals.
- `Defense`: sector view derived from signals.
- `Sheet7 Clusters`: opportunity clusters across sources and countries.
- `Sheet7 Entities`: structured identifier map, not a generic NER dump.
- `Classifier Audit`: classifier disagreement and low-confidence rows.
- `Source Health`: source/runtime status.

## Classifier Rule

Keywords only retrieve candidate windows. They do not decide relevance.

Classification uses:

- Option A: prototype embedding similarity.
- Option B: zero-shot NLI classification.
- Option C later: heavier adjudicator only for disagreement rows.

Rows promote only when classifiers agree or an adjudicator resolves the disagreement.

## First Build PRs

1. Foundation + MCA entity spine.
2. SEC EDGAR + U.S. LDA.
3. EDINET + India IP via EPO/Lens.
4. Canada + UK.
5. EU.
6. APAC complements + production polish.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
pytest
```

Install classifier extras only when running the real classifier:

```bash
pip install -e ".[classifiers]"
```

## Safety

This repo can be public. Do not commit `.env`, API keys, raw filing caches, Google credentials, downloaded source dumps, or private review notes.

