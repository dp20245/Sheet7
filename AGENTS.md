# AGENTS.md

Use `docs/Sheet7_Holistic_PRD.md` for strategy and `docs/Sheet7_Build_Spec.md` for build details.

Build small PRs. Do not add a source connector unless the PRD marks it approved or optional. Do not invent India lobbying filings. Do not use generic NER as an entity source for promoted rows.

Canonical Google Sheet tabs are `Evidence`, `Signals`, `Clusters`, and `RunLog`.

Canonical entity field is `entity_key`; SEC CIK belongs in `entity_key` as `sec:<cik>` and may also appear in `company_ids`.

Secrets must come from environment variables, `SHEET7SECRETS`, or GitHub Secrets.
