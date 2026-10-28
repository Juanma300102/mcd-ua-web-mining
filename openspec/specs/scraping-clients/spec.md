# scraping-clients Specification

## Purpose
How `src/news_politica/sources/` talks to the three outlets: polite requests, bounded retries and a hard stop on anti-bot challenges. It also covers what each client returns (Arc catalog entries, raw documents keeping the source JSON, and articles with the dataset schema), how notes are parsed, and how errors and per-note losses are classified. Created by the `add-scraping-clients` change (Phase 3).
## Requirements
### Requirement: Requests are polite and robots-aware
Every request from `sources/` SHALL go through `PoliteClient`. The client SHALL send an identifiable User-Agent, read each host's robots.txt before the first request to that host, refuse robots-disallowed URLs without sending them, and leave at least 2 s between the starts of two requests to the same host, retries included.

#### Scenario: Disallowed URL is never sent
- **WHEN** robots.txt for a host has `Disallow: /pf/api/` and the client is asked for a `/pf/api/` URL on that host
- **THEN** it raises `Disallowed` and the session receives no request for that URL

#### Scenario: Spacing per host
- **WHEN** the client fetches two URLs on the same host back to back, using a fake clock
- **THEN** the second request starts at least 2 s after the first

#### Scenario: Different hosts are not delayed by each other
- **WHEN** the client fetches one URL on host A and then one on host B
- **THEN** the request to host B is not delayed by the request to host A

#### Scenario: Identifiable User-Agent
- **WHEN** the client sends any request, robots.txt included
- **THEN** the `User-Agent` header names the project and links to its repository

### Requirement: Transient failures are retried a bounded number of times
The client SHALL retry timeouts, connection errors, HTTP 5xx and HTTP 429 up to 3 times, waiting 2, 8 and 32 s, or the `Retry-After` value when it is longer (capped at 300 s). It SHALL raise `TransientError` once the retries are exhausted. Other 4xx responses SHALL be returned to the caller, not raised and not retried.

#### Scenario: Recovers after a 503
- **WHEN** a URL answers 503 once and then 200
- **THEN** `get` returns the 200 response after one retry

#### Scenario: Gives up after four attempts
- **WHEN** a URL answers 500 on every attempt
- **THEN** the client sends 4 requests in total and raises `TransientError`

#### Scenario: Retry-After is honoured
- **WHEN** a URL answers 429 with `Retry-After: 60` and then 200
- **THEN** the retry starts at least 60 s after the 429, measured on the fake clock

#### Scenario: 404 is not retried
- **WHEN** a URL answers 404
- **THEN** `get` returns the 404 response after a single request

### Requirement: Anti-bot challenges stop all traffic to the host
When a response is an anti-bot challenge (HTTP 403 with `cf-mitigated: challenge`, or a "Just a moment..." page), or when a host's robots.txt is not 200, the client SHALL raise `Blocked` and SHALL send no further request to that host for its lifetime. It SHALL NOT retry the request, change its User-Agent or use a browser to get past the challenge.

#### Scenario: Challenge on a note
- **WHEN** a note URL answers 403 with `cf-mitigated: challenge`
- **THEN** `Blocked` is raised and the session received exactly one request for that URL

#### Scenario: Later requests to a blocked host
- **WHEN** a host has been marked blocked and the client is asked for another URL on it
- **THEN** `Blocked` is raised and no request is sent

#### Scenario: Challenge is never treated as a per-note loss
- **WHEN** `fetch_story` or `fetch_month` meets a challenge
- **THEN** `Blocked` propagates to the caller instead of being recorded as a `RawDoc` error

### Requirement: Arc catalog lists every Política URL up to the scraping day
For Infobae and La Nación, `build_catalog` SHALL read every daily sitemap from 2023-12-10 up to the given end day (the scraping day, not the cut-off date) and keep the URLs that the outlet marks as Política. It SHALL dedupe them by URL, keeping the earliest sitemap day, and set each entry's `url_date` from the date in the URL (`/YYYY/MM/DD/` for Infobae, `-nidDDMMYYYY` for La Nación). Sitemap days that still fail after retries SHALL be returned in a list of failed days instead of aborting the crawl.

#### Scenario: Política filter and URL date
- **WHEN** a sitemap fixture holds Política and non-Política URLs
- **THEN** the catalog keeps only the Política URLs, each with the `url_date` parsed from its URL

#### Scenario: URL listed on two days
- **WHEN** the same URL appears in the sitemaps of two different days
- **THEN** the catalog holds one entry for it, with the earlier `sitemap_day`

#### Scenario: A sitemap day fails
- **WHEN** one day's sitemap answers 500 on every attempt and the other days answer 200
- **THEN** the catalog holds the other days' entries and the failing day is in the failed-days list

#### Scenario: Unparseable URL date
- **WHEN** a Política URL has no date the outlet can parse
- **THEN** it is left out of the catalog and counted as dropped

### Requirement: Fetching an Arc note returns a raw document, not an exception, for per-note losses
`fetch_story` SHALL return a `RawDoc` whose payload is the story JSON extracted from `Fusion.globalContent`, never the page HTML, together with the final URL, the status and a UTC fetch time. A note that is gone or unusable SHALL come back as a `RawDoc` with `payload` empty and `error` set: `http_<status>` for a 4xx, `redirected` when the final URL is outside `/politica/`, `no_story` when the page has no `Fusion.globalContent` or its `type` is not `story`, and `disallowed` when robots.txt forbids it.

#### Scenario: Normal note
- **WHEN** a note page fixture with `Fusion.globalContent` answers 200
- **THEN** `fetch_story` returns a `RawDoc` with `error` empty and a payload that loads as the story JSON

#### Scenario: Deleted note
- **WHEN** a note answers 404
- **THEN** `fetch_story` returns a `RawDoc` with `error == "http_404"` and does not raise

#### Scenario: Page without story JSON
- **WHEN** a note answers 200 with HTML that has no `Fusion.globalContent`
- **THEN** `fetch_story` returns a `RawDoc` with `error == "no_story"`

#### Scenario: Redirect out of the section
- **WHEN** a note URL redirects to the outlet's home page
- **THEN** `fetch_story` returns a `RawDoc` with `error == "redirected"` and `final_url` set to the home page

### Requirement: MisionesOnline returns every Política post of a month
`fetch_month` SHALL query the WordPress REST API for category 7, from the first day of the month to the first day of the next month in site time, with `per_page=100` and `_embed=author,wp:term`. It SHALL follow pages until `X-WP-TotalPages` and return one `RawDoc` per post, whose payload is the post JSON without `_links`. A listing page that is not 2xx after retries SHALL raise `SourceError`, so a month is never returned incomplete.

#### Scenario: Month spanning several pages
- **WHEN** the API reports `X-WP-TotalPages: 3` for a month
- **THEN** `fetch_month` requests pages 1 to 3 and returns one `RawDoc` per post across them

#### Scenario: Listing page fails
- **WHEN** page 2 of a month answers 500 on every attempt
- **THEN** `fetch_month` raises a `SourceError` and returns no partial list

### Requirement: Too many per-note losses fail a partition
`check_losses(docs, max_share=0.10)` SHALL raise `TooManyLosses` when more than `max_share` of the given raw documents have `error` set. Otherwise it SHALL return the number of losses.

#### Scenario: A few deleted notes
- **WHEN** 3 of 100 raw documents have `error` set
- **THEN** `check_losses` returns 3

#### Scenario: Layout change
- **WHEN** 40 of 100 raw documents have `error == "no_story"`
- **THEN** `check_losses` raises `TooManyLosses`

### Requirement: Parsing is pure and yields the dataset schema
`parse(RawDoc) -> Article` SHALL make no network request and read no clock. `Article` SHALL have exactly the 13 columns of the dataset schema in `docs/def.md`. `id` SHALL be the SHA-1 hex of the canonical URL, `fecha_publicacion` a tz-aware datetime at UTC-3, `fecha_scraping` the `RawDoc` fetch time, and `titulo`, `bajada` and `cuerpo` plain text without HTML tags or entities. `cuerpo` SHALL separate paragraphs with a blank line. Missing optional fields SHALL become an empty string, an empty list or `False`. `parse` SHALL raise `ParseError` only when the URL, publish date or title is missing, the payload is not valid JSON, or the `RawDoc` has `error` set.

#### Scenario: Same input, same output
- **WHEN** `parse` runs twice on the same `RawDoc`
- **THEN** both `Article`s are equal

#### Scenario: Publish date in Argentina time
- **WHEN** a story has `first_publish_date` `2024-03-01T02:30:00Z`
- **THEN** `fecha_publicacion` is 2024-02-29 23:30 at UTC-3

#### Scenario: No author
- **WHEN** a story has no `credits.by`
- **THEN** `autor` is "" and no error is raised

#### Scenario: Missing title
- **WHEN** a story has no `headlines.basic`
- **THEN** `parse` raises `ParseError`

### Requirement: Arc notes are parsed with the Phase 2 field rules
For Infobae and La Nación, `cuerpo` SHALL join the text of the `text`, `header` and `list` content blocks in order, recursing into list items, one paragraph per block or list item. Notes made only of `raw_html` blocks (La Nación `subtype` 9 special pages) SHALL have an empty `cuerpo`. `bajada` SHALL come from `subheadlines.basic`, `autor` from `credits.by[].name`, `seccion` from `taxonomy.primary_section._id` and `tags` from `taxonomy.tags[].text`. `fuente_externa` SHALL be "". `es_en_vivo` SHALL be true at Infobae when `subtype == "live-blogging"`, and at La Nación when the URL or headline contains "en vivo" or "minuto a minuto".

#### Scenario: Body made of lists
- **WHEN** a La Nación story's content is mostly `list` blocks with nested items
- **THEN** `cuerpo` includes the text of every list item

#### Scenario: Infobae live blog
- **WHEN** an Infobae story has `subtype` `live-blogging`
- **THEN** `es_en_vivo` is true

#### Scenario: La Nación special page
- **WHEN** a La Nación story has `subtype` 9 and only `raw_html` blocks
- **THEN** `cuerpo` is "" and `parse` does not raise

### Requirement: MisionesOnline posts are parsed with the Phase 2 field rules
`bajada` SHALL be the plain-text excerpt without "[…]", or "" when the excerpt is the start of the body. `fuente_externa` SHALL be the outlet named in a "Fuente: X" within the last 300 characters of the body, upper-cased and stripped of trailing text, or "" when there is none. `seccion` SHALL list every category of the post, so "Nacionales" stays visible. `fecha_publicacion` SHALL come from `date_gmt`, and `es_en_vivo` SHALL be false.

#### Scenario: Hand-written excerpt
- **WHEN** a post's excerpt is not the start of its body
- **THEN** `bajada` is the excerpt as plain text

#### Scenario: Automatic excerpt
- **WHEN** a post's excerpt is the first sentence of its body followed by "[…]"
- **THEN** `bajada` is ""

#### Scenario: Rewrite of a national outlet
- **WHEN** a post body ends with "Fuente: Infobae 👉 MANTENETE INFORMADO"
- **THEN** `fuente_externa` is "INFOBAE"

### Requirement: Tests run offline on fixtures that do not republish note bodies
The `sources/` tests SHALL run without network access, using a fake session and a fake clock. Fixtures SHALL come from real Phase 2 responses but cut every note text field to about 20 words. They SHALL keep block structure and closing "Fuente: X" lines, and SHALL never commit a full note body or a full Arc page.

#### Scenario: No network in tests
- **WHEN** `uv run pytest tests/sources` runs with networking disabled
- **THEN** every test passes

#### Scenario: Fixture text is shortened
- **WHEN** the committed fixtures are scanned
- **THEN** no text field holds more than 200 consecutive characters of note text and no fixture file is a full Arc page

