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
  defs/                    # assets, jobs and schedules
  sources/                 # scraping clients: HTTP client, one module per outlet, parse()
tests/
  fixtures/sources/        # trimmed responses from the phase 2 cache (build_fixtures.py)
notebooks/                 # phase 2 source exploration (probe.py, arc.py, one notebook per outlet)
docs/                      # project definition, source decisions
odd/tasks/                 # task tracking
data/                      # Parquet output (gitignored)
```
