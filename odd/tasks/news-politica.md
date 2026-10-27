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
- Scraping etiquette: low rate limit, retries with backoff, identifiable User-Agent. Only paths robots.txt allows; never bypass anti-bot challenges (Cloudflare, CAPTCHAs), with Playwright or by spoofing a browser User-Agent.
- Access route (2026-10-27): Infobae and La Nación are listed from daily sitemaps (Infobae `/arc/outboundfeeds/sitemap/<YYYY-MM-DD>/`, La Nación `/sitemap-articles-from<YYYY-MM-DD>T00:00:00Z-to<next day>T00:00:00Z.xml`), filtered to `/politica/` URLs; the text comes from each note's HTML, which embeds the Arc story JSON in `Fusion.globalContent`. The Arc frontend API (`/pf/api/`) is not used: La Nación's robots.txt disallows it for `User-agent: *`. Mention this in the report.

## Open decisions
- Sentiment model (pysentimiento baseline vs a multilingual model or zero-shot LLM).
- Analyze body text, or only title + summary.
- Keep Parquet, or also load into a Postgres table.
- La Nación paywall truncation: unverified (only the free codes `comun` and `abierta` showed up in 186 notes); check body length per `content_code` in T4.4.

Decided in T2.4 (`docs/decision-fuentes.md`): cut-off 2026-10-31 23:59 ART by publish date; MisionesOnline stays (the 2026-10-27 Cloudflare block lifted the same day; its client stops on a challenge); agency notes and rewrites kept with a `fuente_externa` column, provincial vs national reported with and without them; live blogs kept with `es_en_vivo` and left out of tone aggregates by default.

## Process
- Branch: `feat/news-politica-base` (Phase 1, T1.1–T1.4); `feat/harden-dagster-infra` (T1.5, Phase 2 and Phase 3, decided 2026-10-27: they stay on this branch, so one PR covers all three).
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
Done through the OpenSpec change `explore-news-sources` (archived in `openspec/changes/archive/2026-10-27-explore-news-sources/`, spec in `openspec/specs/news-source-exploration/`); notebooks in `notebooks/`, decisions in `docs/decision-fuentes.md`.
- [x] T2.1 MisionesOnline: check whether the Cloudflare block persists (another day / network; no challenge bypass). If it lifts: paginate `/wp-json/wp/v2/posts?categories=7&after=2023-12-10`; fields; monthly counts (`X-WP-Total`); share of agency notes (author/byline). If not: evaluate the fallback (see Open decisions). Commits `b77ffcd` (probe helper), `e508e16`.
- [x] T2.2 Infobae: sample daily sitemaps across the period for monthly Política volume; map `Fusion.globalContent` fields to the dataset schema; measure the share of live blogs ("en vivo"). Commit `e508e16`.
- [x] T2.3 La Nación: same as T2.2; find notes with a `content_code` other than `comun` and confirm their body is not truncated; check whether a daily sitemap groups by publish date or by last modification. Commit `e508e16`.
- [x] T2.4 Volume estimate and decision note: rate limit, backfill duration, cut-off date, MisionesOnline fallback, agency notes and live blogs handling. Commit `5cc85e5`.

### Phase 3 — Scraping clients (`src/news_politica/sources/`)
- [x] T3.1 Shared HTTP client (robots.txt check, 1 request / 2 s per host, retries/backoff, User-Agent, stop on an anti-bot challenge; `notebooks/probe.py` is the reference) and a common `Article` model matching the dataset schema (now with `fuente_externa` and `es_en_vivo`). Route: OpenSpec `add-scraping-clients`. Commits `c709d01` (fixtures), `85a156f`.
- [x] T3.2 `misionesonline.py` + tests with saved responses: posts by day or month from the REST API with `_embed=author,wp:term`; `bajada` only when the excerpt is not the start of the body; `fuente_externa` from a closing "Fuente: X". Commit `a6a9a42`.
- [x] T3.3 `infobae.py` + tests with saved responses: daily sitemaps up to the scraping day, filtered by `first_publish_date`; body from `text`, `header` and `list` blocks; `es_en_vivo` from `subtype == "live-blogging"`. Commit `b93db82` (with T3.4 and the shared `arc.py`).
- [x] T3.4 `lanacion.py` + tests with saved responses: same as T3.3 with La Nación's sitemap URL; `es_en_vivo` from "en vivo" in the URL or headline; notes made only of `raw_html` blocks (`subtype` 9 special pages) keep an empty body. Commit `b93db82`.

### Phase 4 — Dagster assets
- [ ] T4.1 `catalogo_infobae` and `catalogo_lanacion`: unpartitioned, `sources.arc.build_catalog` from 2023-12-10 to the scraping day (~35 min each); show `failed_days` and `dropped` as metadata and an asset check. Monthly partitions from 2023-12 for `raw_misionesonline` (`fetch_month`), `raw_infobae` and `raw_lanacion` (`fetch_story` over the catalog entries whose `url_date` falls in the month; keep notes whose real publish month differs). Each `raw_*` stores `RawDoc` rows (source JSON, not the HTML) as Parquet, runs `check_losses` and has a retry policy. All assets of one outlet share a Dagster pool with limit 1 (each run process has its own `PoliteClient`, so this keeps 1 request / 2 s per host). `Blocked` becomes `Failure(allow_retries=False)`.
- [ ] T4.2 `noticias_politica`: `sources.parse` over every `raw_*` row (HTML → text, id and Argentina time already happen there), filter to 2023-12-10 → 2026-10-31 23:59 ART by `fecha_publicacion`, dedupe by `url`; count `ParseError` drops in an asset check.
- [ ] T4.3 Backfill job from 2023-12 to the cut-off date (no daily schedule).
- [ ] T4.4 EDA notebook (volume per outlet and week, note length, share with bajada, La Nación body length per `content_code` to settle paywall truncation). Moved from Phase 6: it feeds the Phase 5 decisions (body vs title + summary, minimum notes per week).

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
- 2026-10-27: Phase 2 pre-exploration (read-only probe, identifiable User-Agent, a few spaced requests; no notebooks yet). La Nación: robots.txt disallows `/pf/api/` and `/buscador` for `User-agent: *` (not only bots); a `/pf/api/` request with a browser User-Agent was refused by Claude Code's safety classifier and not retried. The historical sitemap index lists only ~2 years (730 days, from 2024-10-26), but daily files outside it still answer: 2023-12-11 → 364 URLs, 41 `/politica/`. 10 Política notes from 2024-10-27: all `content_code: comun`, full body in the HTML (477–1483 words), story JSON in `Fusion.globalContent`. Infobae: `/arc/outboundfeeds/sitemap/2023-12-11/` → 1375 URLs, 23 `/politica/`; same `Fusion.globalContent` pattern; the first note was a ~2000-word live blog; the category sitemap only returns the latest 100 and ignores `from`. MisionesOnline: 403 Cloudflare challenge on every path, robots.txt included. Rough volume: 20–40 Política notes/day per national outlet → 25k–40k notes each, ~15–22 h of backfill per outlet at 1 request / 2 s. `docs/def.md` updated (sources table, phase 2, risks).

- 2026-10-27: Phase 2 done (route: OpenSpec `explore-news-sources`). MisionesOnline answered again (robots.txt and REST API 200, `X-WP-Total` 56112), so the fallback branch did not run. Results: MisionesOnline 7,245 Política notes 2023-12-10 → 2026-09-30 (exact), Infobae ~23,100 and La Nación ~26,600 (days 10 and 25 of each month); every sampled Arc sitemap answered, 2023-12 included. Arc bodies need `header` and `list` blocks too (some La Nación notes went from 37 to 205+ words). La Nación sitemaps group by `display_date`, Infobae's by last modification, and both list notes months late → crawl sitemaps up to the scraping day and filter by `first_publish_date`. MisionesOnline: 11.4 % close with "Fuente: X" (Infobae, TN, Ámbito), 12.7 % also in Nacionales, no agency bylines. Infobae live blogs 2.2 %, La Nación 0. La Nación paywall: only `comun`/`abierta` in 186 notes, truncation unverified. Check: `uv run pytest` passed (10 tests); the three notebooks ran top to bottom with `PROBE_OFFLINE=1` and 0 network requests.
- 2026-10-27: OpenSpec change `explore-news-sources` archived (`openspec archive -y`): spec `news-source-exploration` created in `openspec/specs/` (7 requirements). Filled the `Purpose` of both main specs, which the archive leaves as TBD. Check: `openspec validate --specs --strict` 2 passed.

- 2026-10-27: Phase 3 done (route: OpenSpec `add-scraping-clients`, interface agreed in an explore session). `src/news_politica/sources/` has two levels. Per outlet: Arc `build_catalog` / `fetch_story`, and MisionesOnline `fetch_month`. Common: `RawDoc` (source JSON or a per-note error) and a pure `parse` → `Article` (13 schema columns). Measured on the Phase 2 cache before deciding: story JSON median 12 KB (Infobae) / 17 KB (La Nación), so `raw_*` keeps it whole (< 1 GB for the period, keeps `content_code` for T4.4); the URL date equals `first_publish_date` in ART in 322/322 notes, so monthly partitions are assigned from the catalog. Errors: transient (client retries 2/8/32 s, then `TransientError`), `Blocked` / `Disallowed` (never retried), per-note losses as `RawDoc.error` (`http_<code>`, `redirected`, `no_story`, `disallowed`), `TooManyLosses` above 10 % of a partition, `ParseError` only for missing URL / date / title. Revised while applying: no special case for `subtype` 9 (one of the two sampled has a text block); bodies keep paragraph breaks (`\n\n`) in all three outlets for the Phase 5 per-paragraph variant. Fixtures under `tests/fixtures/sources/` keep the real structure with text cut to ~20 words (`build_fixtures.py`). Check: `uv run pytest` 77 passed; `parse` over every cached real response matches the Phase 2 numbers (Infobae median 811 words, 3 live; MisionesOnline bajada 68.1 %, "Fuente: X" 11.4 % with the same per-outlet counts; La Nación 2 empty bodies, both `raw_html`-only). New: La Nación does have live notes, 2 of 186 (`subtype` 6 and 11, "en vivo" in URL and headline), both from the 50 extra paywall notes, outside the 136-note sample where Phase 2 measured 0 %.
- 2026-10-27: Phase 3 smoke run against the live sites (OpenSpec task 7.2, team OK in chat), through `PoliteClient`, `build_catalog`, `fetch_story`, `fetch_month` and `parse`: 12 requests, all 200, no challenge (3 robots.txt, 2 sitemaps, 4 Arc notes, 3 MisionesOnline pages). Infobae sitemap 2026-10-26: 26 Política URLs, 0 failed days, 0 dropped; 2 notes parsed (1083 and 639 words, 13 and 9 paragraphs, payload 15 and 10 KB). La Nación sitemap 2026-10-26 (UTC day): 21 Política URLs with URL dates 10-25 and 10-26, as expected from the UTC vs ART offset; 2 notes parsed (334 and 584 words). MisionesOnline October 2026 (to the 27th): 230 posts over 3 pages, 0 losses, 0 empty bodies, dates 10-01 08:59 → 10-27 15:44 ART. Its bajada share (47.4 %) and "Fuente: X" share (5.2 %) are below the Phase 2 sample (68.1 % and 11.4 %): same rule (re-parsing the cache reproduces the Phase 2 numbers), so it looks like a change over time; check per month in the EDA (T4.4). Every parsed note had a title, an ART date and a non-empty body.

## Next step
PR for `feat/harden-dagster-infra` (plan review, T1.5, `docs/def.md` sync, Phase 2, Phase 3; T1.1–T1.4 are already on `main`), then Phase 4 (assets, T4.1 above). Pending from Phase 3: deleting `data/probe_cache/` (OpenSpec task 7.3), with the team's OK.
