# news-politica

Dataset and sentiment analysis of Argentine political news (Infobae, La Nación and MisionesOnline) published since 2023-12-10. The project definition (objective, data sources, schema and plan) is in [`docs/def.md`](docs/def.md).

**Team:** Carlos Aular, Juan Martin Pedrozo.

## Requirements

- [uv](https://docs.astral.sh/uv/) (Python 3.11+; the repo pins 3.12 in `.python-version`)
- Docker with Compose v2.1+ (Postgres for Dagster's run, schedule and event storage; the start script uses `docker compose up --wait`)

## Setup

```bash
uv sync
cp .env.example .env   # optional: change credentials or the Postgres port
```

## Run Dagster

```bash
scripts/dagster-up.sh
```

The script starts Postgres with `docker compose`, checks the connection, validates the definitions and opens the Dagster UI at http://127.0.0.1:3000. Postgres listens on `127.0.0.1` only, host port `5434` by default (`POSTGRES_PUBLISH_PORT` in `.env`).

If Postgres rejects the credentials after you change `.env`, the Docker volume still has the old password. Run `docker compose down -v` (this deletes the local Dagster history) and try again.

## Backfill

The dataset covers 2023-12-10 to the cut-off, 2026-09-30 23:59 ART. Run it outside Claude Code's sandbox, on a machine that stays awake with Docker up: each Arc outlet takes ~14 h at 1 request / 2 s; MisionesOnline takes a few minutes.

1. `scripts/dagster-up.sh`, then in the UI (Assets) select every asset and click **Materialize all**, all partitions. Dagster runs an asset backfill: the two catalogs (~35 min each), then one run per month and outlet, then `noticias_politica`.
2. Each outlet has its own pool with limit 1 (`dagster.yaml`), so at most one run per outlet is in progress; the three outlets run in parallel.
3. A month that fails with a transient error is retried twice, 5 min apart. A `Blocked` (anti-bot challenge) or `TooManyLosses` failure is not retried: cancel that outlet's remaining runs in the UI (Runs, filter by the asset) instead of letting them fail one by one, and check the site before re-launching.
4. Failed months can be re-launched from the asset's partitions view. `noticias_politica` skips months that are missing, so it can be materialized from a partial backfill.

Files land in `data/<asset>.parquet` and `data/raw_<medio>/<YYYY-MM-DD>.parquet` (`DATA_DIR` overrides `data/`).

## Checks

```bash
uv run pytest
uv run dg check defs
```

## Source exploration notebooks

`notebooks/` holds the phase 2 exploration of each outlet; the decisions are in [`docs/decision-fuentes.md`](docs/decision-fuentes.md). Jupyter lives in its own dependency group:

```bash
uv sync --group notebooks
uv run --group notebooks jupyter lab notebooks/
```

Every request goes through `notebooks/probe.py` (robots.txt check, 2 s between requests to a host, stops on an anti-bot challenge) and is cached in `data/probe_cache/`. To re-run a notebook from the cache only, without touching the sites:

```bash
cd notebooks && PROBE_OFFLINE=1 uv run --group notebooks jupyter nbconvert --to notebook --execute --inplace 02_infobae.ipynb
```

The cache from the phase 2 run (~175 MB of the outlets' pages) was deleted when phase 3 closed, after the test fixtures were built from it. `PROBE_OFFLINE=1` therefore fails until a notebook has run online once and filled the cache again; delete `data/probe_cache/` when you no longer need it.

## Layout

```
docker-compose.yaml        # Postgres for Dagster storage
scripts/dagster-up.sh      # starts Postgres + Dagster
src/news_politica/
  definitions.py           # loads everything under defs/
  dagster_home/dagster.yaml
  defs/                    # assets.py (catalogs, raw_* by month, noticias_politica), io.py (Parquet, client)
  sources/                 # scraping clients: HTTP client, one module per outlet, parse()
tests/
  fixtures/sources/        # trimmed responses from the phase 2 cache (build_fixtures.py)
notebooks/                 # phase 2 source exploration (probe.py, arc.py, one notebook per outlet)
docs/                      # project definition, source decisions
odd/tasks/                 # task tracking
data/                      # Parquet output (gitignored)
```
