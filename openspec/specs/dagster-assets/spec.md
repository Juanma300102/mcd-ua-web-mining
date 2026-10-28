# dagster-assets Specification

## Purpose
The Dagster assets in `src/news_politica/defs/` that turn the scraping clients into the dataset: Arc catalogs, monthly raw partitions per outlet, and the unified `noticias_politica` (2023-12-10 to the 2026-09-30 cut-off). It also covers the proof-of-concept sample (30 Arc notes per month, catalogs from two sitemap days per month), one concurrency pool per outlet, which failures are retried, the period filter and the offline tests. Created by the `add-dagster-assets` change (Phase 4).
## Requirements
### Requirement: Raw assets are partitioned by month up to the cut-off
`raw_infobae`, `raw_lanacion` and `raw_misionesonline` SHALL share a monthly partitions definition from 2023-12 to 2026-09, with one run per partition. Each partition SHALL store one row per `RawDoc` as Parquet, keeping the source JSON payload, and SHALL call `check_losses` before it is stored. An Arc partition SHALL fetch only catalog entries whose `url_date` falls in its month, at most `SAMPLE_PER_MONTH` of them (30, the lowest SHA-1 of the URL), and report how many the month lists.

#### Scenario: Arc month from the catalog
- **WHEN** `raw_infobae` is materialized for 2024-03 with a catalog holding entries dated 2024-02-29, 2024-03-01 and 2024-03-31
- **THEN** it fetches the two March URLs and stores two rows

#### Scenario: Catalog entry outside every partition
- **WHEN** the catalog holds an entry with `url_date` 2019-05-01
- **THEN** no partition fetches it

#### Scenario: Month with more notes than the sample
- **WHEN** the catalog lists 4 notes in March and the sample size is 2
- **THEN** the partition fetches the 2 with the lowest URL hash, and a re-run fetches the same 2

#### Scenario: Too many losses
- **WHEN** more than 10 % of a partition's documents come back with `error` set
- **THEN** the partition fails and nothing is stored for it

### Requirement: Arc catalogs are unpartitioned and report their gaps
`catalogo_infobae` and `catalogo_lanacion` SHALL run `build_catalog` over the sitemap days in `SITEMAP_DAYS` (5 and 20) of every month from 2023-12-10 to the scraping day, merged and deduped by URL, and SHALL attach the number of entries, the failed sitemap days and the dropped URL count as materialization metadata.

#### Scenario: A sitemap day fails
- **WHEN** one sitemap day fails after retries
- **THEN** the catalog is stored and its metadata lists that day under `failed_days`

#### Scenario: Only the sampled sitemap days
- **WHEN** the catalog is built up to 2024-01-31
- **THEN** it requests the sitemaps of 2023-12-20, 2024-01-05 and 2024-01-20 and no other day

### Requirement: Requests to one outlet never run in parallel
Every asset that makes requests SHALL belong to its outlet's pool (`infobae`, `lanacion`, `misionesonline`). The Dagster instance SHALL limit every pool to 1 with run granularity, so at most one run per outlet is in progress at a time.

#### Scenario: Instance pool config
- **WHEN** `dagster.yaml` is loaded
- **THEN** the pools' default limit is 1 and their granularity is `run`

#### Scenario: Assets carry their pool
- **WHEN** the definitions are loaded
- **THEN** each catalog and raw asset has the pool of its outlet and `noticias_politica` has none

### Requirement: Challenges and layout changes are not retried
A raw or catalog asset SHALL be retried by Dagster on `TransientError` or a `SourceError` from a listing page. On `Blocked` or `TooManyLosses` it SHALL fail with `Failure(allow_retries=False)`.

#### Scenario: Blocked host
- **WHEN** a raw partition's client raises `Blocked`
- **THEN** the run fails with a non-retryable failure and makes no further request

#### Scenario: Transient failure
- **WHEN** a raw partition's client raises `TransientError`
- **THEN** the failure is retryable under the asset's retry policy

### Requirement: The unified dataset covers the period once per URL
`noticias_politica` SHALL parse every raw row without `error`, keep the notes with `fecha_publicacion` from 2023-12-10 00:00 to 2026-09-30 23:59:59 ART, drop duplicate `url` values, and store the 13 schema columns as Parquet. It SHALL NOT fail on `ParseError`; it SHALL report the number of such drops and the rows per outlet as metadata.

#### Scenario: Note outside the period
- **WHEN** a raw row parses to a note published 2026-10-01 00:30 ART
- **THEN** it is not in `noticias_politica`

#### Scenario: Unparseable note
- **WHEN** one raw row has no title
- **THEN** `noticias_politica` materializes without it and its metadata reports `parse_errors = 1`

#### Scenario: Same URL twice
- **WHEN** two raw rows parse to the same `url`
- **THEN** `noticias_politica` holds one row for it

### Requirement: Asset tests run offline
The asset tests SHALL materialize the assets with a fake client resource and a temporary data directory, without network access.

#### Scenario: No network
- **WHEN** `uv run pytest tests/defs` runs with networking disabled
- **THEN** every test passes

