## Why

Phase 3 (scraping clients) and Phase 4 (backfill) need facts that only the sources can give: how to list every Política note since 2023-12-10, which fields map to the dataset schema, how many notes there are per month, and how long a polite backfill takes. A first read-only probe on 2026-10-27 changed the plan: Infobae and La Nación can be listed from daily sitemaps and read from each note's HTML (the Arc frontend API `/pf/api/` is disallowed by La Nación's robots.txt), while MisionesOnline, assumed to be the easy source, now answers every request with a Cloudflare challenge. This change turns that probe into reproducible evidence and a go/no-go decision before any client code is written. It covers T2.1–T2.4 in `odd/tasks/news-politica.md`.

## What Changes

- Add a `notebooks` dependency group (Jupyter kernel and runner) and a `notebooks/` folder.
- Add a small exploration helper for notebooks: one polite GET (identifiable User-Agent, fixed delay per host, robots.txt check, no challenge bypass) with an on-disk response cache under `data/` (gitignored), so notebooks can be re-run without hitting the sites again.
- One notebook per outlet:
  - MisionesOnline (T2.1, first): record whether the Cloudflare block persists. If the site answers, measure monthly Política volume via the WordPress REST API (`X-WP-Total`), map fields and measure the share of agency notes. If it does not, check the robots.txt and listing route of the provincial fallback outlets the team picks.
  - Infobae (T2.2): sample daily sitemaps across the period, estimate monthly Política volume, map `Fusion.globalContent` fields to the dataset schema, measure the share of live blogs.
  - La Nación (T2.3): the same as Infobae, plus the `content_code` (paywall) distribution with truncation checks, and whether a daily sitemap groups notes by publish date or by last modification.
- A decision note in `docs/` (T2.4): access route per outlet, rate limit, estimated backfill duration, cut-off date, MisionesOnline go/no-go and fallback, and how to handle agency notes and live blogs.
- Update `docs/def.md` and `odd/tasks/news-politica.md` with the decisions.

No pipeline code: nothing under `src/news_politica/` changes. The helper is throwaway; Phase 3 writes the real HTTP client.

## Capabilities

### New Capabilities
- `news-source-exploration`: how the sources are probed (allowed paths only, identifiable User-Agent, rate limit, cache, no challenge bypass), what each outlet's notebook must establish, and what the decision note must decide before Phase 3 starts.

### Modified Capabilities
<!-- None: `dagster-local-infra` is unchanged. -->

## Impact

- New: `notebooks/` (helper module + three notebooks), `docs/decision-fuentes.md`.
- Changed: `pyproject.toml` and `uv.lock` (new `notebooks` dependency group only; runtime dependencies unchanged), `docs/def.md`, `odd/tasks/news-politica.md`, possibly `README.md` (how to run the notebooks).
- Network: a few hundred spaced requests per outlet to public sitemaps and note pages; none to `/pf/api/` or other robots-disallowed paths.
- Committed notebooks keep counts, field maps and short excerpts only, not full note bodies.
- If MisionesOnline stays blocked, the decision note may swap or drop the provincial outlet, which changes the project's scope (`docs/def.md`, the dataset's `medio` values and the provincial vs national question).
