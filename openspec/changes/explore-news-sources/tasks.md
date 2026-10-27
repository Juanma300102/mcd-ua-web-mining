## 1. Setup

- [x] 1.1 Keep working on `feat/harden-dagster-infra` (team decision, 2026-10-27): Phase 2 lands on the same branch as T1.5, so its PR covers both. Check: `git branch --show-current` is `feat/harden-dagster-infra` and the docs updates from the 2026-10-27 probe are committed before the notebooks.
- [ ] 1.2 Add a `notebooks` dependency group to `pyproject.toml` with `ipykernel`, `jupyterlab` and `nbconvert` at their latest PyPI versions, and run `uv lock`. Check: `uv sync --group notebooks` works, and `uv sync` alone does not install Jupyter.
- [ ] 1.3 Add `notebooks/probe.py` (design decision 3): robots.txt check per host (refuse every request to a host whose robots.txt is not 200), ≥2 s between requests to the same host, identifiable User-Agent, 2xx cache under `data/probe_cache/` with a status/headers sidecar, `is_challenge()`, `story_json()`.
- [ ] 1.4 Add `tests/test_probe.py` with no network (requests mocked): a disallowed path raises before any request; a cached URL makes no request; two uncached URLs on one host are ≥2 s apart (fake clock); a non-2xx response is not cached; a 403 with `cf-mitigated: challenge` is detected; `story_json()` parses a saved Arc page snippet. Check: `uv run pytest` passes.

## 2. MisionesOnline (T2.1, first)

- [ ] 2.1 Before running, agree as a team on 1–3 provincial fallback outlets to check if the block persists, and write them in the notebook's first cell.
- [ ] 2.2 `notebooks/01_misionesonline.ipynb`: record the date and the status/headers of robots.txt and `/wp-json/wp/v2/posts?categories=7&per_page=1` with the project User-Agent.
- [ ] 2.3 If both answer 200: monthly `X-WP-Total` counts from 2023-12-10, field map to the dataset schema from one page per sampled month, and agency-note share (design decision 8).
- [ ] 2.4 If blocked: no further request to MisionesOnline; for each fallback outlet, check robots.txt, the listing route (WordPress REST API or daily sitemaps), whether it reaches 2023-12, and one note's fields.

## 3. Infobae (T2.2)

- [ ] 3.1 `notebooks/02_infobae.ipynb`: fetch `/arc/outboundfeeds/sitemap/<YYYY-MM-DD>/` for days 10 and 25 of each month from 2023-12 to the latest full month; count `/politica/` URLs; estimate notes per month and in total; flag months whose two days differ by more than 2×.
- [ ] 3.2 Read 2 notes per sampled day (first and middle `/politica/` URL) and parse `Fusion.globalContent`.
- [ ] 3.3 Field-map table: one row per dataset column in `docs/def.md`, JSON path, share of notes with a value.
- [ ] 3.4 Live-blog share and which signal matched (design decision 6); body word-count distribution.
- [ ] 3.5 Path date vs sitemap day: count URLs that fall on another day.

## 4. La Nación (T2.3)

- [ ] 4.1 `notebooks/03_lanacion.ipynb`: same as 3.1–3.4 with `/sitemap-articles-from<day>T00:00:00Z-to<next day>T00:00:00Z.xml`, confirming the 2023-12 days answer.
- [ ] 4.2 `content_code` distribution and body word count per code. If no non-`comun` note appears, read up to 50 more likely-premium notes (design decision 5); if still none, state it as unverified.
- [ ] 4.3 Sitemap grouping: `nidDDMMYYYY` vs sitemap day for every sampled URL, plus day-before/day-after overlap for 5 sampled days.

## 5. Decision note (T2.4)

- [ ] 5.1 Write `docs/decision-fuentes.md`: route (listing and text) per outlet, volume and request-count table, rate limit, estimated backfill duration, cut-off date, MisionesOnline go/no-go and fallback, agency notes, live blogs, open items, each number linked to its notebook.
- [ ] 5.2 Update `docs/def.md` (sources table, risks, scope if the provincial outlet changes) and `odd/tasks/news-politica.md` (T2.1–T2.4 status, Open decisions, Progress).
- [ ] 5.3 README: how to install the `notebooks` group, open the notebooks, and delete `data/probe_cache/` when Phase 2 closes.

## 6. Verification

- [ ] 6.1 With a warm cache, run every notebook top to bottom with `uv run jupyter nbconvert --to notebook --execute --inplace` and confirm no request reached the network (helper log or cache-miss counter is 0).
- [ ] 6.2 Check committed notebook outputs: no output longer than 200 consecutive characters of note text and no raw HTML (spec: "Committed notebooks do not republish note bodies").
- [ ] 6.3 `uv run pytest` and `uv run dg check defs` pass (nothing under `src/` changed).
- [ ] 6.4 Commit with Conventional Commit messages and record the hashes next to T2.1–T2.4 in `odd/tasks/news-politica.md`.
