# Feature: news-politica

## Objective
Build a Dagster + uv pipeline that scrapes Política news from Infobae, La Nación and MisionesOnline since 2023-12-10, unifies them into one dataset, scores sentiment, and reports tone evolution per outlet over time. Full project definition: `docs/def.md`.

## Problem / Why
The repo is empty. The course project needs a reproducible dataset plus a sentiment analysis answering: how did the tone of political news change since Dec 2023, and does it differ between a digital national outlet, a traditional national newspaper, and a provincial outlet?

## Scope
- In: the three outlets' Política sections, 2023-12-10 to a fixed cut-off date; title, summary (bajada) and body.
- Out: everything specific to the fake-news project (LightGBM, BERT training, SearXNG, webapp).
- Out (time budget, plan review 2026-10-27): daily incremental schedule, national vs provincial topic classifier, inter-annotator agreement, change-point / time-series models, tone toward the government.

## Constraints and decisions
- Reference repo: `../text-mining/mcd-ua-text-mining/` (Dagster project in `classification/`). Reuse `docker-compose.yaml` (postgres only), `scripts/dagster-up.sh`, `dagster_home/dagster.yaml`, `definitions.py` with `load_from_defs_folder`.
- Layout: Dagster project at the repo root, package `src/news_politica/`.
- Dataset storage: Parquet in `data/` (gitignored). Postgres only stores Dagster metadata.
- Dependencies: latest versions from PyPI (checked 2026-10-26), not the reference repo's pins:
  - `requires-python = ">=3.11,<3.15"` (pandas 3 and pyarrow 26 need 3.11+), `.python-version` 3.12
  - `dagster==1.13.27`, `dagster-postgres>=0.29.27`, `psycopg2-binary>=2.9.13`, `pandas>=3.1.0`, `pyarrow>=26.0.0`, `requests>=2.34.2`, `beautifulsoup4>=4.15.0`, `lxml>=6.1.3`
  - Postgres driver: dagster allows `sqlalchemy<3`, which resolves to 2.1.x, and 2.1 uses psycopg 3 for a bare `postgresql://` URL. With psycopg 3, `dagster-webserver` fails its first storage query ("the connection is closed"), so `dagster.yaml` pins `scheme: postgresql+psycopg2` and psycopg 3 is not a dependency (T1.5).
  - dev: `dagster-webserver==1.13.27`, `dagster-dg-cli==1.13.27`, `pytest>=9.1.1`
  - Phase 5 `sentiment` group: `pysentimiento>=0.7.3` (check that it resolves with pandas 3)
- Scraping etiquette: low rate limit, retries with backoff, identifiable User-Agent. La Nación's robots.txt disallows `/pf/api/` for bots; mention this in the report.

## Open decisions
- Sentiment model (pysentimiento baseline vs a multilingual model or zero-shot LLM).
- Analyze body text, or only title + summary.
- Keep Parquet, or also load into a Postgres table.
- Cut-off date value (e.g. 2026-10-31).
- La Nación fallback if its API doesn't reach 2023-12 or returns truncated paywalled bodies: shorten the period for all outlets, compare only the common range, or swap the outlet (decided in T2.4).
- MisionesOnline agency (syndicated national) notes: exclude, or keep with an `es_agencia` flag (decided in T2.4 from T2.1's numbers).

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
- [x] T1.5 Harden infra (OpenSpec change `harden-dagster-infra`): bind Postgres to `127.0.0.1` in compose; readiness over TCP (`pg_isready -h localhost` healthcheck + `docker compose up --wait`, replacing the script's loop); one `storage: postgres:` block with `scheme: postgresql+psycopg2`; host connection check on psycopg2; `psycopg[binary]` dropped; test that `dagster.yaml` resolves to the psycopg2 driver; `code_location_name = "news-politica"` and `dg check defs` / `dg dev` in the start script. Commits `314c576`, `4e29bb3` (driver revision).

### Phase 2 — Source exploration (notebooks; can be split between team members)
Do T2.3 first: it is the riskiest source and T2.4 is a go/no-go on it.
- [ ] T2.1 MisionesOnline: paginate `/wp-json/wp/v2/posts?categories=7&after=2023-12-10`; fields; monthly counts (`X-WP-Total`); share of agency notes (author/byline).
- [ ] T2.2 Infobae: document the Arc `/pf/api/v3/content/fetch/...` list (Política) and detail endpoints, backward pagination, monthly volume; sitemap fallback.
- [ ] T2.3 La Nación: same as T2.2; confirm the API reaches 2023-12 (the historical sitemap only starts in 2025-09) and that paywalled notes return the full body.
- [ ] T2.4 Volume estimate and decision note: rate limit, backfill duration, cut-off date, La Nación fallback, agency notes handling.

### Phase 3 — Scraping clients (`src/news_politica/sources/`)
- [ ] T3.1 Shared HTTP client (rate limit, retries/backoff, User-Agent) and a common `Article` model matching the dataset schema.
- [ ] T3.2 `misionesonline.py` + tests with saved responses.
- [ ] T3.3 `infobae.py` + tests with saved responses.
- [ ] T3.4 `lanacion.py` + tests with saved responses.

### Phase 4 — Dagster assets
- [ ] T4.1 Monthly partitions from 2023-12; `raw_misionesonline`, `raw_infobae`, `raw_lanacion` (Parquet per partition, retry policy).
- [ ] T4.2 `noticias_politica`: common schema, HTML → plain text, id = hash of canonical URL, dedupe, Argentina timezone.
- [ ] T4.3 Backfill job from 2023-12 to the cut-off date (no daily schedule).
- [ ] T4.4 EDA notebook (volume per outlet and week, note length, share with bajada). Moved from Phase 6: it feeds the Phase 5 decisions (body vs title + summary, minimum notes per week).

### Phase 5 — Sentiment
- [ ] T5.1 Short labeling guide (what counts as positive/neutral/negative, with examples), then hand-label a sample (~300 notes, 100 per outlet) + labeling helper.
- [ ] T5.2 `sentimiento_noticias` with the pysentimiento baseline (title + summary), with a `modelo` column.
- [ ] T5.3 Alternative model; compare accuracy and macro F1; choose one.
- [ ] T5.4 `evolucion_tono`: weekly aggregates per outlet + charts with political milestones. Milestone list with dates in a versioned file (DNU 70/2023, Ley Bases, Oct 2025 legislative elections, at least one Misiones event); compare mean score and negative share 2 weeks before vs after each one.

### Phase 6 — Report
- [ ] T6.2 Report: evolution charts, milestone before/after table, provincial vs national comparison, conclusions, limitations (robots.txt, sentiment is not stance, pysentimiento trained on tweets, agency notes). T6.1 (EDA) moved to T4.4.

## Acceptance criteria
- `uv sync`, `uv run dg check defs` and `uv run pytest` pass.
- `scripts/dagster-up.sh` starts the Dagster UI backed by Postgres.
- The unified Parquet dataset covers all three outlets from 2023-12-10 to the cut-off date (or the range decided in T2.4), with the schema in `docs/def.md`.
- Sentiment and weekly tone assets materialize; the report answers the main question and both secondary questions (milestones, provincial vs national).

## Progress
- 2026-10-26: task list defined.
- 2026-10-26: T1.1 done (route: inline, 4 mechanical files). Check: `uv sync` OK; dagster 1.13.27, pandas 3.1.0, pyarrow 26.0.0 import.

- 2026-10-27: T1.2 done (route: inline, mechanical copy). Check: `docker compose config` OK; `scripts/dagster-up.sh` served the UI on :3000 and created 22 Dagster tables in Postgres (after adding psycopg 3).
- 2026-10-27: T1.3 done (route: inline). Check: `uv run pytest` 1 passed; `uv run dg check defs` OK.
- 2026-10-27: `main` had no commits; added root commit `3933c4a` (docs/def.md as `def.md`) and rebased the branch onto it, so commit hashes above are post-rebase.
- 2026-10-27: T1.4 done (route: inline). README + `def.md` moved to `docs/`.
- 2026-10-27: Review of `69c65fa..d35aece` (high risk: shell script): whole-branch candidate exceeded the reviewer context budget (`uv.lock`), so the range excluding T1.1 was reviewed. Approved and acknowledged (lineage `review-b3a7ab1aaa7eeaf5`). T1.1 (`7f59a2a`) was not reviewed. 8 non-blocking findings: 4 warnings (port bound to all interfaces with default credentials; first-run readiness race; host check uses psycopg2 instead of psycopg 3, reported twice) and 4 suggestions (duplicated pg_isready, triplicated storage block in `dagster.yaml`, smoke test doesn't cover storage). Captured as T1.5.
- 2026-10-27: Plan review against the objective, kept to low-cost changes because of the time budget. Added: La Nación first + paywall check + go/no-go in T2.4; agency share in T2.1; labeling guide in T5.1; milestone list and before/after comparison in T5.4. Moved: EDA from T6.1 to T4.4. Removed: daily schedule (fixed cut-off date instead). Left out: see Scope. `docs/def.md` still describes the daily schedule and the old phase order.
- 2026-10-26: T1.5 done (route: OpenSpec `harden-dagster-infra`, branch `feat/harden-dagster-infra`). Reading dagster-postgres 0.29.27 showed it never imports psycopg2 (all access goes through SQLAlchemy, which resolves to psycopg 3), so the scope added the unified storage block with an explicit scheme and dropped `psycopg2-binary`. Check: `uv run pytest` 2 passed (the new test fails with `scheme: postgresql+psycopg2`); `uv run dg check defs` OK; `scripts/dagster-up.sh` on a fresh volume went healthy and passed the credentials check on the first try, Postgres published on `127.0.0.1:5434`, 22 tables; restarting reused the volume (same `run_storage_id`). Not addressed: the `code_location_name` mismatch warning `dagster dev` prints (pre-existing).
- 2026-10-27: T1.5 revised (`4e29bb3`). Checking the UI over HTTP showed nothing listens on :3000 even though the log prints "Serving dagster-webserver": with psycopg 3 the webserver fails `get_run_storage_id` with `psycopg.OperationalError: the connection is closed`. A plain `DagsterInstance` works with both drivers; the webserver serves HTTP 200 only with psycopg2. This predates T1.5 (a bare `postgresql://` already resolved to psycopg 3), so T1.2's "served the UI" was based on the log line. Root cause not investigated. Fix: pin `postgresql+psycopg2`, drop psycopg 3. Also set `code_location_name` and switched to `dg dev` (`dagster dev` cannot rename the location and is superseded). Check: `uv run pytest` 2 passed (the test fails with `postgresql+psycopg`); `dg check defs` OK; `scripts/dagster-up.sh` → HTTP 200, GraphQL location `news-politica` LOADED, no location-name / supersession / `OperationalError` lines. Note: from Claude Code's sandboxed shell the webserver never binds a port, so this check ran outside the sandbox. OpenSpec change updated and archived (`0424e1d`, spec in `openspec/specs/dagster-local-infra/`). `docs/def.md` updated to the current plan (no daily schedule, new phase order, milestones, out of scope).

## Next step
PR for `feat/harden-dagster-infra` (plan review, T1.5, `docs/def.md` sync; T1.1–T1.4 are already on `main`), then Phase 2 starting with T2.3 (T2.1–T2.2 can run in parallel on the other team member's side).
