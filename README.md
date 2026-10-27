# news-politica

Dataset and sentiment analysis of Argentine political news (Infobae, La Nación and MisionesOnline) published since 2023-12-10. The project definition (objective, data sources, schema and plan) is in [`docs/def.md`](docs/def.md).

**Team:** Carlos Aular, Juan Martin Pedrozo.

## Requirements

- [uv](https://docs.astral.sh/uv/) (Python 3.11+; the repo pins 3.12 in `.python-version`)
- Docker with Compose (Postgres for Dagster's run, schedule and event storage)

## Setup

```bash
uv sync
cp .env.example .env   # optional: change credentials or the Postgres port
```

## Run Dagster

```bash
scripts/dagster-up.sh
```

The script starts Postgres with `docker compose`, checks the connection, validates the definitions and opens the Dagster UI at http://127.0.0.1:3000. Postgres listens on host port `5434` by default (`POSTGRES_PUBLISH_PORT` in `.env`).

If Postgres rejects the credentials after you change `.env`, the Docker volume still has the old password. Run `docker compose down -v` (this deletes the local Dagster history) and try again.

## Checks

```bash
uv run pytest
uv run dg check defs
```

## Layout

```
docker-compose.yaml        # Postgres for Dagster storage
scripts/dagster-up.sh      # starts Postgres + Dagster
src/news_politica/
  definitions.py           # loads everything under defs/
  dagster_home/dagster.yaml
  defs/                    # assets, jobs and schedules
tests/
docs/                      # project definition
odd/tasks/                 # task tracking
data/                      # Parquet output (gitignored)
```
