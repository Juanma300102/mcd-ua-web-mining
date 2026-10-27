## 1. Setup and fixtures

- [x] 1.1 Stay on `feat/harden-dagster-infra` (team decision, 2026-10-27): Phase 3 lands on the same branch as T1.5 and Phase 2, so one PR covers all three. Check: `git branch --show-current` is `feat/harden-dagster-infra`.
- [x] 1.2 Create `src/news_politica/sources/` (empty `__init__.py`) and `tests/sources/` with the `FakeRaw` / `FakeSession` / `FakeClock` helpers from `tests/test_probe.py` copied into `tests/sources/conftest.py` (`test_probe.py` keeps its own). The session can also raise `requests.Timeout` / `ConnectionError` and return a sequence of responses per URL.
- [x] 1.3 Write `tests/fixtures/sources/build_fixtures.py` (design decision 9) and run it against `data/probe_cache/`. Arc outlets get 3–5 story JSONs (a normal note; a list-heavy La Nación note; an Infobae live blog; a La Nación `subtype` 9 note), one page cut to the `<script>` around `Fusion.globalContent`, and one sitemap with ~10 entries. MisionesOnline gets one API page with a hand-written excerpt, an automatic excerpt and a closing "Fuente: X", plus its `X-WP-*` headers. Text fields are cut to ~20 words. Check: a test scans the fixtures (spec: "Fixture text is shortened").

## 2. Models, text helpers and HTTP client (T3.1)

- [x] 2.1 `models.py`: `CatalogEntry`, `RawDoc` and `Article` dataclasses (design decision 1). `Article` field names and order match the 13 schema columns in `docs/def.md`. Check: a test compares `Article` field names with the schema list.
- [x] 2.2 `text.py`: `html_to_text()` (bs4 + lxml, entities unescaped, whitespace collapsed), `article_id()` (SHA-1 hex), `ART` (fixed UTC-3) and `to_art()` for ISO UTC strings. Check: unit tests, including the 2024-03-01T02:30Z → 2024-02-29 23:30 case.
- [x] 2.3 `http.py`: error classes (`SourceError`, `TransientError`, `Blocked`, `Disallowed`, `TooManyLosses`, `ParseError`) and `PoliteClient` with the robots.txt check, per-host spacing, User-Agent, 30 s timeout, redirects with the final URL recorded, and challenge detection (design decision 5).
- [x] 2.4 Retries in `PoliteClient`: timeouts, connection errors, 5xx and 429 get 3 retries at 2/8/32 s, with `Retry-After` honoured up to 300 s. Retries respect the per-host spacing; other 4xx are returned.
- [x] 2.5 Tests for every scenario of the "Requests are polite and robots-aware", "Transient failures are retried a bounded number of times" and "Anti-bot challenges stop all traffic to the host" requirements, with the fake clock. Check: `uv run pytest tests/sources` passes in well under a second of wall time per test.
- [x] 2.6 `check_losses(docs, max_share=0.10)` in `sources/__init__.py` with tests for both of its scenarios.

## 3. MisionesOnline (T3.2)

- [ ] 3.1 `misionesonline.py`: `fetch_month(client, month)` with pagination to `X-WP-TotalPages`, one `RawDoc` per post without `_links`, and `SourceError` when a listing page fails (design decision 7).
- [ ] 3.2 `parse_post(raw)`: the `bajada` rule (excerpt vs start of body), `fuente_externa` (the notebook's `SOURCE` / `TRAILER` regexes on the last 300 characters), `seccion` from all categories, `autor` from embedded authors, `tags`, and `fecha_publicacion` from `date_gmt`.
- [ ] 3.3 Tests on the fixtures for the "MisionesOnline returns every Política post of a month" and "MisionesOnline posts are parsed with the Phase 2 field rules" scenarios (three pages, failing page 2, hand-written and automatic excerpt, "Fuente: Infobae 👉 …").

## 4. Arc shared module (T3.3 / T3.4 base)

- [ ] 4.1 `arc.py`: `ArcOutlet` (name, site, `sitemap_url(day)`, `is_politica(url)`, `url_date(url)`, `is_live(story, url)`), `sitemap_entries(xml)`, and `story_json(html)` (taken from `probe.py`).
- [ ] 4.2 `build_catalog(client, outlet, start, end)`: Política filter, dedupe keeping the earliest `sitemap_day`, `url_date`, dropped-URL count, failed-days list (design decision 4).
- [ ] 4.3 `fetch_story(client, outlet, url)`: `RawDoc` with the story JSON payload, or the per-note errors `http_<code>`, `redirected`, `no_story` and `disallowed`. `Blocked` and `TransientError` propagate.
- [ ] 4.4 `parse_story(raw, outlet)`: `text` / `header` / `list` blocks (recursing into list items), `subtype` 9 → empty body, `canonical_url` prefixed with the site, and the field rules from design decision 3.

## 5. Infobae and La Nación (T3.3, T3.4)

- [ ] 5.1 `infobae.py`: `INFOBAE` outlet (sitemap `/arc/outboundfeeds/sitemap/<YYYY-MM-DD>/`, `/politica/YYYY/MM/DD/` date, live = `subtype == "live-blogging"`).
- [ ] 5.2 `lanacion.py`: `LANACION` outlet (sitemap `/sitemap-articles-from<day>T00:00:00Z-to<day+1>T00:00:00Z.xml`, `-nidDDMMYYYY` date, live = "en vivo" / "minuto a minuto" in the URL or headline).
- [ ] 5.3 `parse(raw)` in `sources/__init__.py`: dispatch by `medio`, raising `ParseError` for a `RawDoc` with `error` set or an unknown `medio`.
- [ ] 5.4 Tests on the fixtures for every scenario of the "Arc catalog lists every Política URL up to the scraping day", "Fetching an Arc note returns a raw document…", "Parsing is pure and yields the dataset schema" and "Arc notes are parsed with the Phase 2 field rules" requirements, for both outlets where the scenario applies.

## 6. Docs and plan

- [ ] 6.1 `odd/tasks/news-politica.md`: mark T3.1–T3.4 with their commits. Rewrite T4.1 to add `catalogo_infobae` / `catalogo_lanacion` (unpartitioned), `raw_*` reading the catalog by `url_date` month, one Dagster pool per outlet with limit 1, `Blocked` → `Failure(allow_retries=False)`, and `check_losses` per partition. In T4.2 drop "HTML → plain text" (now in `parse`) and keep the period filter by `first_publish_date`. Add a Progress entry.
- [ ] 6.2 `docs/def.md`: in Arquitectura, add the catalog step before `raw_*` and say that `raw_*` keeps the source JSON and `noticias_politica` parses it. Update `README.md`'s layout with `src/news_politica/sources/` and `tests/fixtures/sources/`.

## 7. Verification

- [ ] 7.1 `uv run pytest` and `uv run dg check defs` pass; nothing under `src/news_politica/defs/` changed.
- [ ] 7.2 Manual smoke run against the live sites, run outside the sandbox and only with the team's OK: 1 sitemap and 2 Política notes per Arc outlet, plus page 1 of one MisionesOnline month, through `PoliteClient`, `fetch_*` and `parse`. Record in Progress the request count and that every `Article` has a title, date and non-empty body (except `subtype` 9). If a site answers with a challenge, record it and stop.
- [ ] 7.3 Once the fixtures are committed and 7.2 passed, ask the team before deleting `data/probe_cache/` (~175 MB). After deleting it, re-run the notebooks only if needed (they need the cache or the network).
- [ ] 7.4 Commit each group with a Conventional Commit and record the hashes next to T3.1–T3.4 in `odd/tasks/news-politica.md`.
