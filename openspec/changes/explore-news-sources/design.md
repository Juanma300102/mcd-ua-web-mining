## Context

Phase 1 left a Dagster project with no assets. Phase 2 (T2.1–T2.4) must confirm, per outlet, how to list Política notes since 2023-12-10, what fields come back, how many notes there are, and how long a polite backfill takes, and then decide the go/no-go items before Phase 3 writes the scraping clients.

A read-only probe on 2026-10-27 (recorded in the Progress section of `odd/tasks/news-politica.md`) found:

- **La Nación:** robots.txt disallows `/pf/api/` and `/buscador` for `User-agent: *`. The historical sitemap index lists only ~2 years, but daily files outside it still answer (`/sitemap-articles-from2023-12-11T00:00:00Z-to2023-12-12T00:00:00Z.xml` → 364 URLs, 41 under `/politica/`). Each note's HTML embeds the Arc story JSON in `Fusion.globalContent`: headline, subheadline, `content_elements`, credits, taxonomy, dates and `content_restrictions.content_code`. 10 of 10 sampled notes were `comun` with full bodies.
- **Infobae:** `/arc/outboundfeeds/sitemap/2023-12-11/` → 1375 URLs, 23 under `/politica/YYYY/MM/DD/`. Same `Fusion.globalContent` pattern. The category sitemap returns only the latest 100. Live blogs exist (~2000 words).
- **MisionesOnline:** every path, robots.txt included, answers HTTP 403 with `cf-mitigated: challenge`. The WordPress REST API answered on 2026-10-01.

Constraints: only robots-allowed paths, identifiable User-Agent, low rate, no anti-bot bypass (`odd/tasks/news-politica.md`, Constraints). Two team members can split T2.2 and T2.3. Dependencies follow the project rule of latest PyPI versions.

## Goals / Non-Goals

**Goals:**
- Reproducible evidence, in notebooks, for every number the decision note uses.
- A volume and duration estimate good enough to plan the Phase 4 backfill.
- A clear go/no-go on MisionesOnline and a decided fallback.
- Notebooks can be re-run offline from the cache.

**Non-Goals:**
- Scraping clients, the `Article` model or Dagster assets (Phase 3 and 4).
- A full download of any outlet.
- Getting past the Cloudflare challenge in any way.
- Using the Arc frontend API (`/pf/api/`) on either Arc outlet.
- Sentiment work or EDA of the final dataset (T4.4).

## Decisions

**1. Notebooks in `notebooks/`, one per outlet, numbered by run order.** `01_misionesonline.ipynb`, `02_infobae.ipynb`, `03_lanacion.ipynb`. `docs/def.md` already reserves `notebooks/` for EDA and report charts, and one file per outlet lets the two team members work in parallel without merge conflicts in notebook JSON. Alternative: one notebook for all three. Rejected: conflicts and a long run.

**2. A `notebooks` dependency group, not runtime dependencies.** Add `ipykernel`, `jupyterlab` and `nbconvert` (latest versions on PyPI when applying) to `[dependency-groups] notebooks`. Parsing uses `requests`, `lxml`, `beautifulsoup4` and `pandas`, which are already runtime dependencies. Alternative: put Jupyter in `dev`. Rejected: `dev` is what CI-style checks (`pytest`, `dg`) need, and Jupyter pulls in a large tree.

**3. A throwaway helper, `notebooks/probe.py`, instead of starting T3.1 early.** About 60 lines:
- `get(url) -> Response`: checks `urllib.robotparser` for the host (fetched once and cached; if robots.txt is not 200, every request to that host is refused), waits until 2 s have passed since the last request to that host, sends `User-Agent: news-politica-research/0.1 (+<repo URL>)`, and caches 2xx bodies under `data/probe_cache/<host>/<sha1(url)>` with a small JSON sidecar (status, headers, fetched-at).
- `is_challenge(resp)`: true for a 403 with `cf-mitigated: challenge` or a "Just a moment..." page. Callers stop on it; the helper never retries a challenge.
- `story_json(html) -> dict`: extracts `Fusion.globalContent` from an Arc page.

Alternative: write the shared HTTP client (T3.1) first and use it here. Rejected: T3.1's retry, backoff and rate settings depend on what Phase 2 measures, and the helper keeps Phase 2 independent of the package layout. The helper is not imported from `src/`. Phase 3 can copy the robots and `story_json` logic.

Known limit: `urllib.robotparser` does not understand `*` wildcards inside a path (La Nación has `/*undefined*`, `/*?utm_*`). All the paths this change uses are plain prefixes (`/sitemap-articles-…`, `/arc/outboundfeeds/sitemap/…`, `/politica/…`, `/wp-json/…`), and `/pf/api/` is a plain `Disallow`, so the check is still correct for them.

**4. Sampling: days 10 and 25 of each month.** From 2023-12 to the latest full month that is ~35 months × 2 = ~70 sitemap requests per Arc outlet, ~2.5 minutes at 2 s each. Fixed days are reproducible and avoid cherry-picking. The monthly estimate is the mean of the two days × days in the month. Alternative: every day. Rejected: ~1050 requests per outlet for a number we only need to the nearest ~20%. Alternative: random days with a seed. Rejected: no clear gain over fixed days.

**5. Note sample: 2 notes per sampled day.** The first and the middle `/politica/` URL of each sampled sitemap: ~140 notes per Arc outlet, ~5 minutes. That gives the field-presence table, word counts, live-blog share and the La Nación `content_code` distribution. If no non-`comun` note shows up, the La Nación notebook reads up to 50 more notes from the sampled sitemaps whose URL or headline hints at an opinion or analysis piece, and if none shows up then, it reports the check as unverified (spec: "No non-common note in the sample").

**6. Live blog detection.** A note counts as a live blog if its URL or headline contains "en vivo" / "minuto a minuto", or its Arc `subtype` / `label` marks it as live. The notebook reports which signal matched, so T2.4 can pick a rule for the clients.

**7. Sitemap grouping check (La Nación).** For each sampled URL, compare the `nidDDMMYYYY` date with the sitemap day; for 5 sampled days, also fetch the day before and after and count URLs listed more than once. Infobae gets the same check from the `/YYYY/MM/DD/` path date. This decides how strict Phase 4's dedupe must be.

**8. MisionesOnline first, and stop on a challenge.** The notebook checks robots.txt and one REST call. If both are 200, it runs the original T2.1 plan: monthly `X-WP-Total` counts with `categories=7&after=…&before=…&per_page=1&_fields=id` (~35 requests), one page of 100 posts per sampled month for the field map, and the agency share from the author name and the first and last body paragraphs (byline patterns such as "(NA)", "Télam", "NA", "Noticias Argentinas", "Fuente:"). If not, it records the status and checks the fallback outlets the team names in T2.1. For each, it checks robots.txt, whether there is a WordPress REST API or daily sitemaps, and one request to the earliest listing page. Picking the fallback is a team decision recorded in the decision note.

**9. Decision note in Spanish, `docs/decision-fuentes.md`.** Same language as `docs/def.md`, which it feeds. Sections: route per outlet, volume and duration table, rate limit, cut-off date, MisionesOnline decision, agency notes, live blogs, open items. Every number links to its notebook. Alternative: put it in `docs/def.md` directly. Rejected: `def.md` is the project definition; the note keeps the evidence and reasoning, and `def.md` gets the outcome.

**10. Commit notebooks with outputs, trimmed.** Outputs make the evidence reviewable on GitHub without re-running. Cells show counts, tables and excerpts of at most 200 characters, never full bodies or raw HTML, which would republish copyrighted text. Alternative: strip all outputs (e.g. `nbstripout`). Rejected: reviewers would have to re-run against the live sites.

## Risks / Trade-offs

- [The sites change between the probe and the backfill (Cloudflare on MisionesOnline appeared within a month)] → The decision note records the date of every check, and the Phase 3 clients detect a challenge and stop instead of failing silently.
- [Fixed-day sampling misses spikes (elections, Ley Bases votes)] → The estimate is for planning the backfill, not for analysis; Phase 4 counts the real volume. The notebook flags months where the two sampled days differ by more than 2×.
- [140 notes may not include a paywalled one] → Decision 5 widens the search; otherwise paywall truncation stays a named open risk, and Phase 4's EDA (T4.4) checks word counts per `content_code` on the full dataset.
- [The cache under `data/` can hold copyrighted HTML on a laptop] → It is gitignored and only used locally to avoid re-hitting the sites. The README says to delete `data/probe_cache/` when Phase 2 closes.
- [Notebook JSON produces noisy diffs and conflicts] → One notebook per outlet and per person; commit with outputs only after a clean top-to-bottom run.
- [The decision may drop or swap the provincial outlet] → The note states the impact on the research questions, and `docs/def.md` is updated in the same change so the scope stays consistent.

## Migration Plan

No migration. After pulling: `uv sync --group notebooks`, then open the notebooks with `uv run jupyter lab`. Rollback is reverting the commits. `data/probe_cache/` can be deleted at any time.

## Open Questions

- Which provincial outlets to check as MisionesOnline fallbacks (team decision at the start of T2.1, only needed if the block persists).
- Whether to contact MisionesOnline for access, and who does it. That is outside the notebooks but feeds the decision note.
- Cut-off date: proposed 2026-10-31 in the plan, confirmed in T2.4 against the estimated backfill duration.
