# Feature: news-politica

## Objective
Build a Dagster + uv pipeline that scrapes Política news from Infobae, La Nación and MisionesOnline since 2023-12-10, unifies them into one dataset, scores sentiment, and reports tone evolution per outlet over time. Full project definition: `docs/def.md`.

## Problem / Why
The repo is empty. The course project needs a reproducible dataset plus a sentiment analysis answering: how did the tone of political news change since Dec 2023, and does it differ between a digital national outlet, a traditional national newspaper, and a provincial outlet?

## Scope
- In: the three outlets' Política sections, 2023-12-10 to the scraping cut-off date; title, summary (bajada) and body.
- Out: everything specific to the fake-news project (LightGBM, BERT training, SearXNG, webapp).

## Constraints and decisions
- Reference repo: `../text-mining/mcd-ua-text-mining/` (Dagster project in `classification/`). Reuse `docker-compose.yaml` (postgres only), `scripts/dagster-up.sh`, `dagster_home/dagster.yaml`, `definitions.py` with `load_from_defs_folder`.
- Layout: Dagster project at the repo root, package `src/news_politica/`.
- Dataset storage: Parquet in `data/` (gitignored). Postgres only stores Dagster metadata.
- Dependencies: latest versions from PyPI (checked 2026-10-26), not the reference repo's pins:
  - `requires-python = ">=3.11,<3.15"` (pandas 3 and pyarrow 26 need 3.11+), `.python-version` 3.12
  - `dagster==1.13.27`, `dagster-postgres>=0.29.27`, `psycopg2-binary>=2.9.13`, `pandas>=3.1.0`, `pyarrow>=26.0.0`, `requests>=2.34.2`, `beautifulsoup4>=4.15.0`, `lxml>=6.1.3`
  - `psycopg[binary]>=3.3.6`: dagster allows `sqlalchemy<3`, which resolves to 2.1.x, and 2.1 uses psycopg 3 as the default `postgresql://` driver. `dagster-postgres` only declares psycopg2, so without this dependency Postgres storage fails with `No module named 'psycopg'`.
  - dev: `dagster-webserver==1.13.27`, `dagster-dg-cli==1.13.27`, `pytest>=9.1.1`
  - Phase 5 `sentiment` group: `pysentimiento>=0.7.3` (check that it resolves with pandas 3)
- Scraping etiquette: low rate limit, retries with backoff, identifiable User-Agent. La Nación's robots.txt disallows `/pf/api/` for bots; mention this in the report.

## Open decisions
- Sentiment model (pysentimiento baseline vs a multilingual model or zero-shot LLM).
- Analyze body text, or only title + summary.
- Keep Parquet, or also load into a Postgres table.

## Process
- Branch: `feat/news-politica-base`.
- Postgres host port defaults to 5434 (text-mining uses 5433).
- TDD: not configured (source: no project/session setting) → ordinary functional checks. Runner: `uv run pytest`.
- Delivery strategy: `ask-on-risk`. The forecast is well over 400 changed lines in total, so ship one PR slice per phase.
- Every task closes with a Conventional Commit; record its hash next to the task.

## Tasks

### Phase 1 — Base
- [x] T1.1 Scaffold the uv project: `pyproject.toml` (versions above, `[tool.dg]` config), `.python-version`, `.gitignore` (`data/`, `.venv`, `.env`). Commit `7f59a2a`.
- [x] T1.2 Copy and adapt infra: `docker-compose.yaml` (postgres only, renamed volume), `scripts/dagster-up.sh` (`DAGSTER_HOME` → `src/news_politica/dagster_home`), `dagster.yaml`, `.env.example`. Commit `69c65fa`.
- [x] T1.3 `definitions.py` + empty `defs/` + `tests/` smoke test. Commit `cdb1684`.
- [x] T1.4 README with setup/run steps; move `def.md` to `docs/`. Commit `d35aece`.
- [ ] T1.5 (proposed, from review; awaiting approval) Harden infra: bind Postgres to `127.0.0.1` in compose; make the readiness wait check over TCP (`pg_isready -h localhost`) so a fresh volume can't fail with a false credentials error; switch the host connection check to psycopg 3, the driver Dagster actually uses; add a test that loads `dagster.yaml` and resolves the psycopg 3 dialect.

### Phase 2 — Source exploration (notebooks; can be split between team members)
- [ ] T2.1 MisionesOnline: paginate `/wp-json/wp/v2/posts?categories=7&after=2023-12-10`; fields; monthly counts (`X-WP-Total`).
- [ ] T2.2 Infobae: document the Arc `/pf/api/v3/content/fetch/...` list (Política) and detail endpoints, backward pagination, monthly volume; sitemap fallback.
- [ ] T2.3 La Nación: same as T2.2; confirm the API reaches 2023-12 (the historical sitemap only starts in 2025-09).
- [ ] T2.4 Volume estimate and decision note (rate limit, backfill duration).

### Phase 3 — Scraping clients (`src/news_politica/sources/`)
- [ ] T3.1 Shared HTTP client (rate limit, retries/backoff, User-Agent) and a common `Article` model matching the dataset schema.
- [ ] T3.2 `misionesonline.py` + tests with saved responses.
- [ ] T3.3 `infobae.py` + tests with saved responses.
- [ ] T3.4 `lanacion.py` + tests with saved responses.

### Phase 4 — Dagster assets
- [ ] T4.1 Monthly partitions from 2023-12; `raw_misionesonline`, `raw_infobae`, `raw_lanacion` (Parquet per partition, retry policy).
- [ ] T4.2 `noticias_politica`: common schema, HTML → plain text, id = hash of canonical URL, dedupe, Argentina timezone.
- [ ] T4.3 Jobs + daily schedule; run the backfill from 2023-12.

### Phase 5 — Sentiment
- [ ] T5.1 Hand-label a sample (~300 notes, 100 per outlet) + labeling helper.
- [ ] T5.2 `sentimiento_noticias` with the pysentimiento baseline (title + summary), with a `modelo` column.
- [ ] T5.3 Alternative model; compare accuracy and macro F1; choose one.
- [ ] T5.4 `evolucion_tono`: weekly aggregates per outlet + charts with political milestones.

### Phase 6 — Report
- [ ] T6.1 EDA notebook (volume per outlet and month, note length).
- [ ] T6.2 Report: evolution charts, conclusions, limitations (robots.txt, sentiment is not stance).

## Acceptance criteria
- `uv sync`, `uv run dg check defs` and `uv run pytest` pass.
- `scripts/dagster-up.sh` starts the Dagster UI backed by Postgres.
- The unified Parquet dataset covers all three outlets from 2023-12-10, with the schema in `docs/def.md`.
- Sentiment and weekly tone assets materialize; the report answers the main question.

## Progress
- 2026-10-26: task list defined.
- 2026-10-26: T1.1 done (route: inline, 4 mechanical files). Check: `uv sync` OK; dagster 1.13.27, pandas 3.1.0, pyarrow 26.0.0 import.

- 2026-10-27: T1.2 done (route: inline, mechanical copy). Check: `docker compose config` OK; `scripts/dagster-up.sh` served the UI on :3000 and created 22 Dagster tables in Postgres (after adding psycopg 3).
- 2026-10-27: T1.3 done (route: inline). Check: `uv run pytest` 1 passed; `uv run dg check defs` OK.
- 2026-10-27: `main` had no commits; added root commit `3933c4a` (docs/def.md as `def.md`) and rebased the branch onto it, so commit hashes above are post-rebase.
- 2026-10-27: T1.4 done (route: inline). README + `def.md` moved to `docs/`.
- 2026-10-27: Review of `69c65fa..d35aece` (high risk: shell script): whole-branch candidate exceeded the reviewer context budget (`uv.lock`), so the range excluding T1.1 was reviewed. Approved and acknowledged (lineage `review-b3a7ab1aaa7eeaf5`). T1.1 (`7f59a2a`) was not reviewed. 8 non-blocking findings: 4 warnings (port bound to all interfaces with default credentials; first-run readiness race; host check uses psycopg2 instead of psycopg 3, reported twice) and 4 suggestions (duplicated pg_isready, triplicated storage block in `dagster.yaml`, smoke test doesn't cover storage). Captured as T1.5.

## Next step
T1.5 if approved; then the Phase 1 PR slice, then Phase 2 (T2.1–T2.3 can be split between team members).
