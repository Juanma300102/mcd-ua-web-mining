## ADDED Requirements

### Requirement: Probes use only allowed paths and never bypass anti-bot measures
Every request made while exploring the sources SHALL go to a path the outlet's robots.txt allows for `User-agent: *`, SHALL send an identifiable User-Agent that names the project, and SHALL NOT try to pass an anti-bot challenge (Cloudflare challenge, CAPTCHA) by any means, including a browser User-Agent, a headless browser or a challenge solver.

#### Scenario: Disallowed path
- **WHEN** a notebook asks the helper for a URL under a path the outlet's robots.txt disallows (for example La Nación's `/pf/api/`)
- **THEN** the helper raises an error and sends no request

#### Scenario: Challenge response
- **WHEN** a response is HTTP 403 with a `cf-mitigated: challenge` header or a challenge page
- **THEN** the helper records the status and headers, does not retry with other headers or tools, and the notebook reports the source as blocked

#### Scenario: robots.txt itself is blocked
- **WHEN** the outlet's robots.txt cannot be read
- **THEN** the helper sends no other request to that host

### Requirement: Probes are rate limited and cached
The exploration helper SHALL wait at least 2 seconds between requests to the same host and SHALL cache every successful response on disk under `data/` (gitignored), keyed by URL, so that re-running a notebook does not repeat requests that already succeeded.

#### Scenario: Re-run with a warm cache
- **WHEN** a notebook that already ran to the end is run again
- **THEN** every response it needs comes from the cache and no request reaches the outlet

#### Scenario: Two requests in a row
- **WHEN** two uncached URLs on the same host are fetched one after the other
- **THEN** the second request starts at least 2 seconds after the first

#### Scenario: Failed response
- **WHEN** a request returns a non-2xx status
- **THEN** the status is recorded but the response is not cached as a success

### Requirement: Each Arc outlet notebook establishes the listing route, volume and field map
For Infobae and La Nación, a notebook SHALL list Política notes from daily sitemaps, filtering URLs under `/politica/`, for at least two days per month from 2023-12 to the latest full month, and SHALL report: daily and estimated monthly Política note counts, a map from the note's `Fusion.globalContent` JSON to every column of the dataset schema in `docs/def.md` (or why a column has no source), and the share of live-blog notes in the sample of notes read.

#### Scenario: Earliest month reached
- **WHEN** the notebook requests the daily sitemap for a day in 2023-12 after the 10th
- **THEN** it reports whether the sitemap answers and how many `/politica/` URLs it lists

#### Scenario: Field map complete
- **WHEN** the notebook has parsed at least one note per sampled month
- **THEN** it shows a table with one row per dataset column, the JSON path it comes from, and the share of sampled notes where the value is present

#### Scenario: Volume estimate
- **WHEN** the sampled sitemaps have been counted
- **THEN** the notebook shows the estimated Política notes per month and in total from 2023-12-10 to the latest full month

### Requirement: La Nación notebook checks paywall truncation and sitemap grouping
The La Nación notebook SHALL report the distribution of `content_restrictions.content_code` in the sampled notes and the body word count per code, and SHALL check whether a daily sitemap lists notes by publish date or by last modification.

#### Scenario: Non-common content code found
- **WHEN** a sampled note has a `content_code` other than `comun`
- **THEN** the notebook reports its body word count next to the `comun` notes' word counts and states whether the body looks truncated

#### Scenario: No non-common note in the sample
- **WHEN** no sampled note has a `content_code` other than `comun`
- **THEN** the notebook says so explicitly and the decision note lists paywall truncation as unverified

#### Scenario: Sitemap grouping
- **WHEN** the notebook compares each sampled URL's date (the `nidDDMMYYYY` suffix) with the sitemap day and with the adjacent days' sitemaps
- **THEN** it reports how many URLs fall on a different day and how many appear in more than one daily sitemap

### Requirement: MisionesOnline notebook records access status before anything else
The MisionesOnline notebook SHALL first record the response status of robots.txt and of the WordPress REST API with the project's User-Agent, with the date. If the site answers, it SHALL report monthly Política counts from `X-WP-Total` (category 7, from 2023-12-10), the field map and the share of agency notes. If the site is blocked, it SHALL check the robots.txt and the note listing route of each provincial fallback outlet the team names.

#### Scenario: Site answers
- **WHEN** robots.txt and `/wp-json/wp/v2/posts?categories=7` answer HTTP 200
- **THEN** the notebook reports monthly counts, the field map and the share of notes whose author or byline points to an agency

#### Scenario: Site still blocked
- **WHEN** robots.txt or the REST API answers with a challenge
- **THEN** the notebook records the status, makes no further request to MisionesOnline, and runs the fallback checks

### Requirement: Decision note closes Phase 2 before clients are written
A decision note in `docs/` SHALL state, for each outlet in the final scope, the listing route, the text route, the rate limit, the estimated number of requests and backfill duration; and SHALL decide the cut-off date, the MisionesOnline go/no-go and fallback, and how agency notes and live blogs are handled. `docs/def.md` and `odd/tasks/news-politica.md` SHALL be updated to match it.

#### Scenario: Every decision has evidence
- **WHEN** the decision note is reviewed
- **THEN** each number and decision points to the notebook (and cell or table) it comes from

#### Scenario: Provincial outlet dropped or swapped
- **WHEN** the decision is to swap or drop MisionesOnline
- **THEN** the note states the impact on the provincial vs national question, and `docs/def.md` reflects the new scope

### Requirement: Committed notebooks do not republish note bodies
Notebooks committed to the repository SHALL contain counts, field maps, word counts and short excerpts (at most 200 characters per note), and SHALL NOT contain full note bodies or raw HTML.

#### Scenario: Output check before commit
- **WHEN** a notebook is committed
- **THEN** no output cell contains more than 200 consecutive characters of a note's text or raw page HTML
