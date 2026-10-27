## 1. Infra

- [x] 1.1 `dagster.yaml`: add `concurrency: pools: default_limit: 1, granularity: run` (design decision 3). Check: a test loads the instance config and asserts both values.
- [x] 1.2 `defs/io.py`: Parquet IO manager on `UPathIOManager`, base `DATA_DIR` or `<repo>/data` (design decision 6), and the client resource. Revised while applying: the resource is a plain `PoliteClient` (`dg.ResourceParam`), not a `ConfigurableResource` wrapper; each run process loads the definitions and gets its own client, and tests pass a client on the fake session.

## 2. Assets (T4.1, T4.2)

- [x] 2.1 In `defs/assets.py` (no separate module): monthly partitions 2023-12 → 2026-09, `CUTOFF` = 2026-10-01 00:00 ART (exclusive).
- [x] 2.2 `defs/assets.py`: `catalogo_infobae`, `catalogo_lanacion` with metadata; `raw_infobae`, `raw_lanacion`, `raw_misionesonline` with pool, `BackfillPolicy.multi_run(1)`, `RetryPolicy(max_retries=2, delay=300)`, `check_losses`, and `Blocked` / `TooManyLosses` → `Failure(allow_retries=False)` (design decisions 2 and 4).
- [x] 2.3 `noticias_politica`: parse, period filter, dedupe by `url`, metadata `parse_errors` and rows per outlet.

## 3. Tests

- [x] 3.1 `tests/defs/`: materialize one month of `raw_infobae` (from a small catalog) and one of `raw_misionesonline` with fake clients on the `tests/sources` fixtures and `tmp_path`; then `noticias_politica` over them. Cover the spec scenarios: month selection, out-of-range entry, too many losses, `Blocked` not retryable, period filter, `ParseError` count, dedupe, pools on the assets. Check: `uv run pytest` and `uv run dg check defs` pass offline.

## 4. Docs

- [x] 4.1 README: how to launch the backfill from the UI, how to cancel one outlet after a `Blocked`, keep the machine awake. `odd/tasks/news-politica.md` and `docs/def.md`: cut-off 2026-09-30, T4.3 as an asset backfill (no job), T4.4 left for after the data.

## 5. Backfill (outside the sandbox, team's OK)

- [ ] 5.1 Start `scripts/dagster-up.sh`, materialize `raw_misionesonline` for one month and the two catalogs; check in the UI that only one run per outlet is in progress (pool limit works).
- [ ] 5.2 Launch the backfill of all `raw_*` partitions, then `noticias_politica`. Record in Progress: duration, `failed_days`, losses per outlet, `parse_errors`, rows per outlet.
- [ ] 5.3 Commit each group with a Conventional Commit and record the hashes next to T4.1–T4.3.
