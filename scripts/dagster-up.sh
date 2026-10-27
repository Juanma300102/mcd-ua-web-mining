#!/usr/bin/env bash
# Start PostgreSQL (Docker) if needed, then Dagster with persistent storage.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is not installed or not in PATH" >&2
  exit 1
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export POSTGRES_USER="${POSTGRES_USER:-dagster}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-dagster}"
export POSTGRES_DB="${POSTGRES_DB:-dagster}"
export POSTGRES_PUBLISH_PORT="${POSTGRES_PUBLISH_PORT:-5434}"

export DAGSTER_HOME="$ROOT/src/news_politica/dagster_home"

# Drop DAGSTER_POSTGRES_* inherited from the shell (e.g. conda); they can
# contradict POSTGRES_* from .env and make Dagster fail to connect from the host.
unset DAGSTER_POSTGRES_HOST DAGSTER_POSTGRES_PORT DAGSTER_POSTGRES_USER DAGSTER_POSTGRES_PASSWORD DAGSTER_POSTGRES_DB || true

# Same instance as docker-compose (volume user/password/database).
export DAGSTER_POSTGRES_HOST="127.0.0.1"
export DAGSTER_POSTGRES_PORT="$POSTGRES_PUBLISH_PORT"
export DAGSTER_POSTGRES_USER="$POSTGRES_USER"
export DAGSTER_POSTGRES_PASSWORD="$POSTGRES_PASSWORD"
export DAGSTER_POSTGRES_DB="$POSTGRES_DB"

# --wait blocks until the compose healthcheck (pg_isready over TCP) passes.
echo "Starting PostgreSQL and waiting for it to accept connections..."
if ! docker compose up -d --wait --wait-timeout 90; then
  echo "" >&2
  echo "PostgreSQL did not start or did not become healthy in time." >&2
  echo "If the error says 'port is already allocated', host port ${POSTGRES_PUBLISH_PORT} is in use." >&2
  echo "Set another value in .env (template: .env.example), e.g. POSTGRES_PUBLISH_PORT=5435" >&2
  echo "Otherwise inspect it with: docker compose ps / docker compose logs postgres" >&2
  exit 1
fi

echo "Checking credentials inside the container (POSTGRES_*)..."
if ! docker compose exec -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
  psql -h localhost -p 5432 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc 'select 1' \
  >/dev/null 2>&1; then
  echo "" >&2
  echo "Error: PostgreSQL rejects POSTGRES_USER / POSTGRES_PASSWORD for the current volume." >&2
  echo "Usual cause: the Docker volume was created with another password; changing .env does not update it." >&2
  echo "Fix (deletes this dev database): run 'docker compose down -v' from the repo root and retry." >&2
  exit 1
fi

uv sync

echo "Checking the connection from the host (as Dagster will)..."
if ! uv run python -c "
import os, sys
import psycopg2
try:
    psycopg2.connect(
        host=os.environ['DAGSTER_POSTGRES_HOST'],
        port=int(os.environ['DAGSTER_POSTGRES_PORT']),
        user=os.environ['DAGSTER_POSTGRES_USER'],
        password=os.environ['DAGSTER_POSTGRES_PASSWORD'],
        dbname=os.environ['DAGSTER_POSTGRES_DB'],
        connect_timeout=8,
    ).close()
except Exception as exc:
    print(exc, file=sys.stderr)
    sys.exit(1)
"; then
  echo "TCP connection from the host to port ${DAGSTER_POSTGRES_PORT} failed." >&2
  echo "Check with: docker compose ps" >&2
  exit 1
fi

# dg reads the project from pyproject.toml ([tool.dg]), including code_location_name.
uv run dg check defs

# Create the outlet pools up front. Dagster 1.13.27 creates a pool from `default_limit` only after
# the queue pass that first sees it, so on a fresh database the first runs of one outlet would
# start together (seen on 2026-10-27).
for pool in infobae lanacion misionesonline; do
  uv run dagster instance concurrency set "$pool" 1 >/dev/null
done

echo "Dagster + Postgres ready"
exec uv run dg dev
