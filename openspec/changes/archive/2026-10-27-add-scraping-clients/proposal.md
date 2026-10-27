## Why

Phase 2 settled how each outlet is reached (`docs/decision-fuentes.md`), but the only code that talks to the sites is the throwaway `notebooks/probe.py`. Phase 4 needs real clients under `src/news_politica/sources/` that the Dagster assets can call for a 14–16 h backfill per Arc outlet, so their interface, error handling and parsing rules have to be fixed and tested first. The cut-off is 2026-10-31 and the backfill can only start on 2026-11-01, so the clients must be ready right after it. This change covers T3.1–T3.4 in `odd/tasks/news-politica.md`.

## What Changes

- New package `src/news_politica/sources/` with a two-level interface:
  - **Per-outlet level.** Arc outlets (Infobae, La Nación): read one daily sitemap into catalog entries, get a URL's own date, and fetch one note as a raw document. MisionesOnline: fetch every Política post of one month as raw documents (the WordPress API filters by publish date, so it needs no catalog).
  - **Common level, used by Phase 4.** `RawDoc` (the source's own JSON plus fetch metadata or a per-note error) and a pure `parse(RawDoc) → Article`, where `Article` has exactly the 13 columns of the dataset schema in `docs/def.md`.
- A URL catalog function for Arc outlets: crawl the daily sitemaps from 2023-12-10 to the scraping day, keep `/politica/` URLs, dedupe them, and assign each one a month from the date in its URL (the URL date matched `first_publish_date` in Argentina time in 322 of 322 sampled notes). Phase 4 materializes it once per outlet, unpartitioned.
- A polite shared HTTP client: robots.txt check, identifiable User-Agent, at least 2 s between requests to a host, bounded retries with backoff for transient failures, and a hard stop on anti-bot challenges.
- An error taxonomy that says who retries what: transient (the client retries, then Dagster may retry the partition), host blocked or disallowed (never retried), per-note loss (recorded in the raw output, not raised), parse error (only for missing required fields). There is also a guard that fails a month when more than 10 % of its notes are lost.
- HTML → plain text moves into `parse` (bs4), because MisionesOnline's `bajada` and `fuente_externa` rules need plain text. T4.2 (`noticias_politica`) only unions, filters the period by `first_publish_date` and dedupes.
- Offline tests with fixtures built from the Phase 2 cache. Fixtures keep the real structure but shorten the note text, so the repo does not republish note bodies.
- Plan updates: T4.1 in `odd/tasks/news-politica.md` gains the catalog assets, a one-per-outlet concurrency pool and the "blocked is not retried" rule.

No Dagster assets or jobs (Phase 4), no new dependencies (`requests`, `beautifulsoup4` and `lxml` are already runtime dependencies), and no change to the dataset schema.

## Capabilities

### New Capabilities
- `scraping-clients`: how `sources/` talks to the outlets (politeness, retries, stopping on a challenge), what each client returns (catalog entries, raw documents, articles), how notes are parsed into the dataset schema, and how errors and per-note losses are classified.

### Modified Capabilities
<!-- None: `dagster-local-infra` and `news-source-exploration` are unchanged. -->

## Impact

- New: `src/news_politica/sources/` (HTTP client, models, text helpers, Arc shared module, one module per outlet), `tests/sources/` with fixtures under `tests/fixtures/sources/`.
- Changed: `odd/tasks/news-politica.md` (T3.x status, T4.1/T4.2 scope), `docs/def.md` (architecture: catalog step, where text cleaning happens), `README.md` layout section.
- Not changed: `pyproject.toml` / `uv.lock`, `src/news_politica/defs/`, the dataset schema.
- Network: none from tests. A short manual smoke run against the live sites (a few requests per outlet) checks that the fixtures still match.
- After the fixtures are committed, `data/probe_cache/` (~175 MB) can be deleted, as planned in Phase 2.
