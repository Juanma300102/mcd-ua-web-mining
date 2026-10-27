## Context

`sources/` gives Arc `build_catalog` / `fetch_story`, MisionesOnline `fetch_month`, `check_losses` and a pure `parse` (spec `scraping-clients`). Each `PoliteClient` keeps 1 request / 2 s per host only inside its own process. Volume: ~660 Infobae and ~760 La Nación notes per month (~22–25 min per partition at 2 s), ~210 MisionesOnline posts per month (3 pages). Catalog: ~1,050 sitemaps, ~35 min per outlet. The deliverable is due in a couple of days, so the design keeps only what the backfill needs.

## Goals / Non-Goals

**Goals:** materialize `noticias_politica` for the three outlets, 2023-12-10 → 2026-09-30, without breaking the scraping etiquette, with a failed month retryable on its own.

**Non-Goals:** daily schedule, coverage checks, partial catalog re-crawl, automatic backfill cancellation, the EDA notebook, sentiment.

## Decisions

**1. Cut-off 2026-09-30 23:59 ART; 34 monthly partitions.** `MonthlyPartitionsDefinition(start_date="2023-12-01", end_date="2026-10-01")`, shared by the three `raw_*`. October 2026 would only be complete on 2026-11-01, after the delivery. The catalogs still crawl up to the scraping day, so notes listed late in the sitemaps are caught.

**2. Asset graph.**

```
catalogo_infobae  (pool infobae)  ──▶ raw_infobae  [monthly] ──┐
catalogo_lanacion (pool lanacion) ──▶ raw_lanacion [monthly] ──┼──▶ noticias_politica
                    raw_misionesonline [monthly] (pool misionesonline) ──┘
```

- Catalog: `build_catalog(client, OUTLET, end=date.today())` → DataFrame of `CatalogEntry`; metadata `entries`, `failed_days` (list as text), `dropped`.
- `raw_<arc>`: catalog rows whose `url_date` falls in the partition month → `fetch_story` each → DataFrame of `RawDoc`. Catalog rows outside every partition (old notes edited later, notes after the cut-off) are ignored. Metadata `notes`, `losses`.
- `raw_misionesonline`: `fetch_month(client, month)`.
- All `raw_*`: `check_losses` before returning; `BackfillPolicy.multi_run(1)` so each month is its own run and retry unit.
- `noticias_politica`: loads every raw partition, `parse` each row (skipping `error` rows, counting `ParseError`), keeps `fecha_publicacion` in [2023-12-10 00:00, 2026-10-01 00:00) ART, `drop_duplicates("url")`. Metadata: rows per outlet, `parse_errors`. Memory (~1 GB of JSON strings) is accepted; partitioning it is the fallback if it does not fit.

**3. Concurrency: one pool per outlet, limit 1, run granularity.** Each network asset sets `pool=<medio>`. `dagster.yaml` gets:

```yaml
concurrency:
  pools:
    default_limit: 1
    granularity: run
```

An unconfigured pool has no limit, so the limit must be set. `run` granularity makes the queued run coordinator launch a run only when its pool has a free slot. With `op` granularity, the ~100 backfill runs would start and wait inside the queue's run slots, and runs of one outlet could keep the others from starting. `noticias_politica` has no pool.

**4. Errors.**

| Error | Handling |
| :---- | :---- |
| `TransientError`, `SourceError` (listing page) | `RetryPolicy(max_retries=2, delay=300)` |
| `Blocked` | `Failure(allow_retries=False)` with the host in the description |
| `TooManyLosses` | `Failure(allow_retries=False)`: a layout change does not fix itself in 5 min |
| `ParseError` | counted in `noticias_politica`, never raised |

A `Blocked` outlet keeps failing its remaining partitions one by one (one robots.txt request each). The README says to cancel that outlet's backfill by hand.

**5. Client as a resource.** A plain `PoliteClient` passed as resource `client` and typed `dg.ResourceParam[PoliteClient]` (revised while applying: a `ConfigurableResource` wrapper added nothing). Each run process loads the definitions again, so each run has its own client. Tests pass a `PoliteClient` on the `FakeSession` / `FakeClock` from `tests/sources/conftest.py`.

**6. Storage: Parquet IO manager on `UPathIOManager`.** Base path `data/` at the repo root (`DATA_DIR` env var overrides it, tests use `tmp_path`). Files: `data/<asset>.parquet` and `data/<asset>/<YYYY-MM-DD>.parquet` for partitions. `UPathIOManager` already loads all partitions of an upstream asset as a dict when the downstream asset is unpartitioned. Datetimes stay tz-aware; `tags` is a list column.

**7. Backfill without a job (T4.3).** In the UI: select all assets → Materialize → all partitions. The asset backfill daemon (started by `dg dev`) runs the catalogs, then the months, then `noticias_politica`. Run order: MisionesOnline is quick and runs alongside the other two, since every outlet has its own pool.

## Risks / Trade-offs

- [The 14 h backfill does not finish before the delivery] → Launch it as soon as the assets pass their tests, overnight; partial months can still feed `noticias_politica` (materialize it over the months that finished).
- [Sleeping laptop or Docker stop mid-backfill] → Failed or interrupted months are re-launched from the UI; finished months are kept.
- [`noticias_politica` runs out of memory] → Fallback: read partitions one at a time or partition it by month.
- [`granularity: run` behaves differently than expected in 1.13.27] → Task 5.1 checks it in the UI before launching the full backfill: only one run per outlet in progress.
