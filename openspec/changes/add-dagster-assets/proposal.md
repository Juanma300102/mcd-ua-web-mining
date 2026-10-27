## Why

The scraping clients in `src/news_politica/sources/` are done and tested, but `defs/` is empty: there is no way to run the backfill and get the dataset. The deliverable is due in a couple of days, and the Arc backfill takes ~14 h per outlet, so this change wraps the clients in the fewest Dagster assets that produce `noticias_politica` and starts the backfill as soon as possible. It covers T4.1–T4.3 in `odd/tasks/news-politica.md`, cut down to the minimum.

## What Changes

- **Cut-off moves from 2026-10-31 to 2026-09-30 23:59 ART** (decided 2026-10-27, delivery in a couple of days). October 2026 cannot be complete before the delivery, and the Phase 2 counts already end on 2026-09-30. Monthly partitions run from 2023-12 to 2026-09 (34 months).
- `catalogo_infobae` and `catalogo_lanacion`: unpartitioned, `build_catalog` from 2023-12-10 to the scraping day; `failed_days` and `dropped` shown as metadata.
- `raw_misionesonline`, `raw_infobae` and `raw_lanacion`: monthly partitions, one run per partition, `RawDoc` rows as Parquet, `check_losses` per partition.
- One concurrency pool per outlet with limit 1 and run granularity, set in `dagster.yaml`, so 1 request / 2 s per host holds across runs.
- Retry rules: `TransientError` and `SourceError` from a listing page are retried by a Dagster `RetryPolicy`; `Blocked` and `TooManyLosses` fail without retry.
- `noticias_politica`: unpartitioned, `parse` over every raw row, filter to 2023-12-10 → 2026-09-30 23:59 ART, dedupe by `url`, `ParseError` drops in metadata.
- A small Parquet IO manager under `data/`.
- The backfill is a Dagster asset backfill launched from the UI, documented in the README. There is no backfill job: one job cannot mix partitioned and unpartitioned assets.

Left out on purpose (time): a monthly coverage check, re-crawling only the catalog's failed days, an automatic stop of an outlet's backfill after `Blocked`, a per-outlet job, and the T4.4 EDA notebook (it needs the data and stays in the plan as the next step).

## Capabilities

### New Capabilities
- `dagster-assets`: the assets that turn the scraping clients into the dataset: catalogs, monthly raw partitions, the unified `noticias_politica`, their storage, concurrency, retry rules and period filter.

### Modified Capabilities
<!-- None: `scraping-clients` is used as is. -->

## Impact

- New: `src/news_politica/defs/` modules (assets, IO manager, resources), `tests/defs/` with offline materialization tests.
- Changed: `src/news_politica/dagster_home/dagster.yaml` (concurrency block), `README.md` (how to run the backfill), `odd/tasks/news-politica.md` and `docs/def.md` (cut-off 2026-09-30, T4.3 without a job, T4.4 status).
- Not changed: `src/news_politica/sources/`, `pyproject.toml` / `uv.lock` (`universal_pathlib` already comes with dagster).
- Network: none from tests. The backfill itself makes ~50k requests over ~14 h per Arc outlet and must run outside Claude Code's sandbox, on a machine that stays awake with Docker up.
