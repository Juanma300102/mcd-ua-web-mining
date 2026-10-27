## Context

Phase 2 (`docs/decision-fuentes.md`, spec `news-source-exploration`) fixed the access route per outlet:

| Outlet | Listing | Text |
| :---- | :---- | :---- |
| MisionesOnline | WordPress REST API, `categories=7`, `after`/`before` in site time (UTC-3), `_embed=author,wp:term`, 100 per page | The same post JSON (`content.rendered`) |
| Infobae | Daily sitemap `/arc/outboundfeeds/sitemap/<YYYY-MM-DD>/` | Note HTML, Arc story JSON in `Fusion.globalContent` |
| La Nación | Daily sitemap `/sitemap-articles-from<day>T00:00:00Z-to<day+1>T00:00:00Z.xml` | Same as Infobae |

Facts that shape this design. The first three come from Phase 2; the rest were measured on 2026-10-27 from the Phase 2 cache (`data/probe_cache/`), offline:

- Arc sitemaps list notes months after publication (up to 492 days at Infobae, 338 at La Nación), so a month's notes can appear in any later sitemap. Decision T2.4: crawl sitemaps up to the scraping day and filter by `first_publish_date`.
- Rate limit: 1 request every 2 s per host, no parallel requests to one host. Arc backfill ≈ 14–16 h per outlet; MisionesOnline < 5 min.
- MisionesOnline was behind a Cloudflare challenge for part of 2026-10-27. The client stops on a challenge and never tries to get past it.
- The date in the URL (`/politica/YYYY/MM/DD/` at Infobae, `-nidDDMMYYYY` at La Nación) equals `first_publish_date` converted to Argentina time in 136/136 Infobae and 186/186 La Nación notes.
- The Arc story JSON is small: median 12 KB (Infobae) and 17 KB (La Nación), max 59 KB. A MisionesOnline post with `_embed` is ~15 KB. All raw documents for the period come to well under 1 GB.
- Sitemaps carry only `loc` and `lastmod` (plus images at Infobae). Their days are UTC days.
- All 576 cached responses are 200: there is no evidence of what Arc returns for a deleted or moved note.

`notebooks/probe.py` already has the robots.txt check, per-host spacing, challenge detection and `story_json()`, with injectable `session`, `clock` and `sleep`. `notebooks/arc.py` has the block-to-text logic, and `01_misionesonline.ipynb` has the `bajada` and "Fuente: X" rules. This change turns that logic into package code. It has no response cache and adds retries.

## Goals / Non-Goals

**Goals:**
- An interface Phase 4 can wrap directly: one unpartitioned catalog asset per Arc outlet, monthly `raw_*` partitions, and `noticias_politica` calling `parse`.
- Raw output that can be re-parsed without scraping again.
- Error handling that never retries an anti-bot challenge, keeps going when a single note disappears, and fails loudly when an outlet's layout changes.
- Tests that run offline in seconds, with real response structure.

**Non-Goals:**
- Dagster assets, partitions, jobs, retry policies or concurrency pools (Phase 4; this change only records what they need).
- A response cache or resume within a partition (see Decision 8).
- Getting past Cloudflare or any other challenge, rotating User-Agents, or using Playwright.
- Using the Arc frontend API (`/pf/api/`).
- Changing the dataset schema.

## Decisions

**1. Two levels: per-outlet functions, and a common `RawDoc` → `Article` contract.**

```
sources/
  http.py            PoliteClient, the error classes
  models.py          CatalogEntry, RawDoc, Article
  text.py            html_to_text(), article_id(), ART (UTC-3)
  arc.py             ArcOutlet config, sitemap_entries(), build_catalog(), fetch_story(), parse_story()
  infobae.py         INFOBAE = ArcOutlet(...)
  lanacion.py        LANACION = ArcOutlet(...)
  misionesonline.py  fetch_month(), parse_post()
  __init__.py        parse(RawDoc) -> Article (dispatch by medio), check_losses()
```

```
CatalogEntry  medio, url, url_date (date), lastmod (str), sitemap_day (date)
RawDoc        medio, url, final_url, status (int), fetched_at (datetime, UTC),
              payload (str | None: story or post JSON), error (str | None)
Article       id, medio, url, fecha_publicacion, titulo, bajada, cuerpo, autor,
              seccion, tags, fuente_externa, es_en_vivo, fecha_scraping
```

The listing step differs by outlet: Arc needs a catalog, while WordPress lists and returns the text in one call. That is why there is no common "list, then fetch" interface. What the three share is "a month → raw documents" and "a raw document → Article".

Alternative: one `Client` class per outlet with `scrape_month(month) → list[Article]`. Rejected because it hides the catalog, which every Arc partition needs, and it makes re-parsing require a re-scrape.

**2. Raw output keeps the source's JSON as is, not `Article`.** `RawDoc.payload` is the full story JSON (Arc) or post JSON (WordPress) as a string. It is small (< 1 GB for the period), it keeps fields the schema leaves out (`content_code` for the T4.4 paywall check, `subtype`, `display_date`), and a parsing fix only re-runs `noticias_politica`. For Arc, the payload is the extracted `Fusion.globalContent`, never the page HTML (~15 GB). For WordPress it is one post, with `_links` dropped.

Alternative: trim the story to the schema fields. Rejected: it saves 10–20 % and loses `content_code`. `content_code` stays out of `Article` (decided in the explore session): T4.4 reads it from the payload.

**3. `parse` is pure and lives in `sources/`.** `parse(raw: RawDoc) -> Article` makes no requests and uses no clock: `fecha_scraping` comes from `RawDoc.fetched_at`. It runs in Phase 4's `noticias_politica`, but it is written and tested here because it holds most of the per-outlet rules. HTML → text uses BeautifulSoup with `lxml` (`get_text(" ")`, collapsed whitespace, entities unescaped), which replaces the regex in `notebooks/arc.py`. T4.2 no longer cleans HTML.

Field rules (from `docs/decision-fuentes.md`):
- `id` = SHA-1 hex of the canonical URL. Arc: `canonical_url` prefixed with the site. WordPress: `link`.
- `fecha_publicacion` = Arc `first_publish_date` / WordPress `date_gmt`, both parsed as UTC and converted to a fixed UTC-3 offset (Argentina has had no DST since 2009). It is a tz-aware datetime.
- Arc `cuerpo` = `text`, `header` and `list` blocks in order, with list items recursed and joined by blank lines. `subtype` 9 (special pages built with `raw_html` blocks) gives an empty body.
- Arc `bajada` = `subheadlines.basic`; `autor` = `credits.by[].name` joined with ", "; `seccion` = `taxonomy.primary_section._id`; `tags` = `taxonomy.tags[].text`.
- `es_en_vivo`: Infobae `subtype == "live-blogging"`; La Nación "en vivo" / "minuto a minuto" in the URL or headline; MisionesOnline always false.
- MisionesOnline `bajada` = the plain-text excerpt (with "[…]" removed), set to "" when it is the start of the body (first 60 characters, as in the notebook). `fuente_externa` = the outlet in a closing "Fuente: X" within the last 300 characters, cleaned of trailers with the notebook's regexes and upper-cased; otherwise "". `seccion` = the post's categories joined with ", ", so "Nacionales" stays visible. `autor` = the embedded author names.
- `fuente_externa` is "" for Arc outlets.
- Optional fields missing from the JSON become "" or `[]`. `parse` raises `ParseError` only when the URL, publish date or title is missing, or when the payload is not JSON or the `RawDoc` has `error` set.

**4. The catalog is a plain function; Phase 4 makes it an asset.** `build_catalog(client, outlet, start=2023-12-10, end=<scraping day>) -> Catalog` walks every daily sitemap (≈1,060 per outlet, ~35 min, ~0.9 GB at Infobae) and keeps URLs that pass `outlet.is_politica`. It dedupes by URL, keeping the earliest `sitemap_day`, and sets `url_date = outlet.url_date(url)`. A URL whose date cannot be parsed is dropped and counted. It returns the entries plus a list of the sitemap days that failed after retries, so that one bad day does not throw away 35 minutes of crawling. Phase 4 shows the failed days as metadata and an asset check.

Monthly partitioning uses `url_date`, which matches `first_publish_date` in every sampled note. `raw_*` does not drop a note whose real publish month differs from its URL month: the period filter by `first_publish_date` stays in `noticias_politica`, so no note can fall between partitions.

Alternative: partition the catalog by sitemap month. Rejected for a one-shot backfill: every `raw_*` partition would depend on all catalog partitions anyway, and a failure costs at most ~35 minutes.

**5. `PoliteClient` (in `http.py`), based on `probe.py` without the cache.**
- `get(url) -> Response`: checks robots.txt (fetched once per host per client), raises `Disallowed` before sending anything to a disallowed URL, and waits until ≥ 2 s have passed since the last request to that host. Retries count against the same spacing. It sends `User-Agent: news-politica/0.1 (+https://github.com/Juanma300102/mcd-ua-web-mining)` with a 30 s timeout and follows redirects, recording the final URL.
- Retries: timeouts, connection errors, 5xx and 429 get up to 3 retries (4 attempts) after 2, 8 and 32 s. A `Retry-After` header is used when it is longer, capped at 300 s. When the retries run out, the client raises `TransientError`. Other 4xx statuses are returned to the caller, not raised.
- Challenge: a 403 with `cf-mitigated: challenge`, or a "Just a moment..." page, marks the host as blocked and raises `Blocked`. Every later request to that host raises `Blocked` without being sent. A robots.txt that is not 200 also blocks the host, as in `probe.py`.
- `session`, `clock`, `sleep` and `min_interval` are injectable, so tests check spacing and backoff with a fake clock.

`urllib3.Retry` on an `HTTPAdapter` was considered and rejected: it sleeps internally, so retries could not share the per-host spacing or be tested with a fake clock, and it cannot tell a challenge 403 from another 403.

Known limit, carried over from Phase 2: `urllib.robotparser` ignores `*` wildcards inside paths. Every path the clients use is a plain prefix, and `/pf/api/` is a plain `Disallow`.

**6. Error taxonomy: classify by who retries.**

| Class | Raised by | Cases | Who handles it |
| :---- | :---- | :---- | :---- |
| `TransientError` | `PoliteClient` | Retries exhausted on timeout / connection / 5xx / 429 | Phase 4 `RetryPolicy` retries the partition |
| `Blocked` | `PoliteClient` | Anti-bot challenge, robots.txt not 200 | Nobody: Phase 4 turns it into `Failure(allow_retries=False)` |
| `Disallowed` | `PoliteClient` | robots.txt disallows the URL | For a note: `fetch_story` records it as a loss. For a sitemap or API page: it propagates (a config bug) |
| per-note loss | `fetch_story` (returns, no raise) | 404/410 or another 4xx (`http_<code>`), redirect outside `/politica/` (`redirected`), no `Fusion.globalContent` or `type != "story"` (`no_story`), disallowed (`disallowed`) | Stored as a `RawDoc` with `error` set and counted by `check_losses` |
| `TooManyLosses` | `check_losses(docs, max_share=0.10)` | > 10 % of a partition's documents have `error` set | Fails the partition: a layout change, not a few deleted notes |
| `ParseError` | `parse` | Missing URL / publish date / title, unreadable payload, `RawDoc` with `error` | `noticias_politica` drops the note and counts it (asset check in Phase 4) |

All of them subclass `SourceError`. A sitemap or WordPress page that is not 2xx after retries is not a per-note loss. For WordPress it raises `SourceError`, because a month's listing must be complete. For a sitemap day it is recorded in the catalog's failed days (Decision 4).

The 10 % threshold is a guess, since no error has been seen yet. It is a parameter, and the first real backfill months will show whether it needs to change.

**7. MisionesOnline fetches by month with pagination.** `fetch_month(client, month) -> list[RawDoc]` requests `after=<first day>T00:00:00&before=<first day of next month>T00:00:00&categories=7&per_page=100&_embed=author,wp:term&page=N` until it reaches `X-WP-TotalPages` (≈210 posts → 3 pages). It returns one `RawDoc` per post, all sharing the page's `fetched_at`. Posts linking to a sister site (0.7 %) are kept with their own `link`.

**8. No response cache in the package.** Losing a failed partition costs ~25 min and the Arc outlets have never blocked. A per-URL JSON cache (< 1 GB) would allow resuming within a partition. It is the first thing to add if the backfill starts failing midway, and it fits behind `fetch_story` without changing the interface.

**9. Fixtures from the Phase 2 cache, with shortened text.** A one-off script, `tests/fixtures/sources/build_fixtures.py`, reads `data/probe_cache/` and writes:
- per Arc outlet: 3–5 story JSONs covering a normal note, a list-heavy note (La Nación), a live blog (Infobae) and a `subtype` 9 note (La Nación); one real page cut down to the `<script>` around `Fusion.globalContent`; one sitemap cut to ~10 `<url>` entries, at least one of them `/politica/`;
- MisionesOnline: one API page with posts that show a hand-written excerpt, an automatic excerpt and a closing "Fuente: X", plus its `X-WP-*` headers.

Each text field is cut to its first ~20 words while keeping block types and the closing "Fuente: X" line. The repo then keeps structure, not note bodies, which is the same rule the Phase 2 notebooks followed. The script is committed so the fixtures can be rebuilt while the cache exists. Error-path fixtures (404, challenge page, redirect) are written by hand in the tests.

Alternative: commit full responses. Rejected: it republishes copyrighted text, and Arc pages are 215–380 KB each.

## Risks / Trade-offs

- [Arc changes its page layout during the backfill] → `fetch_story` records `no_story`, and `check_losses` fails the month once losses pass 10 %, instead of producing 16 h of empty notes.
- [Dagster runs two partitions of one outlet in parallel, each process with its own `PoliteClient`, which breaks 1 request / 2 s per host] → Out of scope here. T4.1 must put every asset of an outlet in one Dagster pool with limit 1 (added to `odd/tasks/news-politica.md` by this change).
- [A `RetryPolicy` retries a `Blocked` partition and hits a challenged site again] → `Blocked` is its own class. T4.1 must raise `Failure(allow_retries=False)` for it (also recorded in the plan).
- [Unknown behaviour for deleted or moved Arc notes (no evidence in the cache)] → They are handled defensively as per-note losses, and `final_url` is recorded so the first real months can be inspected.
- [URL date ≠ publish month for some note outside the 322 sampled] → `raw_*` keeps the note anyway, and `noticias_politica` filters by `first_publish_date`, so the note lands in the right period.
- [A sitemap day fails and its notes are missing from the catalog] → The failed days are returned and shown by Phase 4. Re-running the catalog later only costs time.
- [Shortened fixtures miss a real-world edge case] → A manual smoke run (task 7.2) fetches 1 sitemap and 2 notes per Arc outlet and 1 MisionesOnline page from the live sites, and parses them.
- [The 10 % loss threshold is arbitrary] → It is a parameter. Revisit it after the first months of the backfill.

## Open Questions

- Branch (decided 2026-10-27): Phase 3 stays on `feat/harden-dagster-infra`, with T1.5 and Phase 2, in one PR.
- Team split: T3.1 + T3.2 (HTTP client, models, MisionesOnline) and T3.3 + T3.4 (Arc) can go in parallel once groups 1–2 of `tasks.md` (models and HTTP client) are merged.
