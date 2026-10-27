## Context

Phase 1 left a working local stack: `docker-compose.yaml` runs `postgres:16-alpine`, `scripts/dagster-up.sh` starts it, checks it and runs `dagster dev`, and `src/news_politica/dagster_home/dagster.yaml` points run, schedule and event-log storage at it.

Findings from reading the installed packages (dagster 1.13.27, dagster-postgres 0.29.27, SQLAlchemy 2.1.6, psycopg 3.3.6):

- `dagster_postgres` never imports `psycopg2`. Every connection goes through `sqlalchemy.create_engine(pg_url_from_config(...))`. With SQLAlchemy 2.1 the bare `postgresql://` URL resolves to the `psycopg` (3) dialect. `pg_url_from_config` on our config returns `postgresql://u:p@h:5434/d` and `create_engine(...).dialect.driver == "psycopg"`.
- The `postgres_db` config shape accepts `scheme` (default `"postgresql"`), and the instance config accepts a unified `storage: postgres:` block.
- The official Postgres image initialises a fresh volume with a temporary server that listens only on the Unix socket, then restarts with TCP enabled. `pg_isready` without `-h` uses the socket, so it reports ready during that window, and the script's next step (`psql -h localhost`) fails and prints the "volume has another password" message.

## Goals / Non-Goals

**Goals:**
- Postgres reachable only from the host machine.
- "Ready" means ready over TCP, checked in one place.
- The host check and the config both use the driver Dagster really uses, and a test fails if that stops being true.
- A shorter `dagster.yaml` with no repeated blocks.

**Non-Goals:**
- Changing the Postgres image, credentials scheme or port defaults.
- Moving the dataset into Postgres (still an open decision in the plan).
- Updating `docs/def.md` (daily schedule and phase order drift); tracked separately.
- CI setup.

## Decisions

**1. Bind to `127.0.0.1` in compose.** `ports: "127.0.0.1:${POSTGRES_PUBLISH_PORT:-5434}:5432"`. Alternative: make the bind address an env var. Rejected: no one needs LAN access, and one more knob adds nothing.

**2. Readiness via the compose healthcheck plus `docker compose up -d --wait`.** The healthcheck becomes `pg_isready -h localhost -U ... -d ...`, and the script calls `docker compose up -d --wait` (with `--wait-timeout 90`, matching today's 90 s loop). The manual `for ... pg_isready` loop and the second `pg_isready` call are removed. Alternative: keep the loop and add `-h localhost` to it. Rejected: the readiness rule would then live in two places (compose and script) that can drift, which is what the review flagged. On a `--wait` failure the script prints a hint pointing at `docker compose ps` / `docker compose logs postgres`, and keeps the existing "port is already allocated" hint.

The in-container `psql -h localhost ... select 1` check stays: `pg_isready` does not check the password, and that step is what detects a volume created with other credentials.

**3. Host check with psycopg 3.** Replace `import psycopg2; psycopg2.connect(..., dbname=..., connect_timeout=8)` with `import psycopg; psycopg.connect(..., dbname=..., connect_timeout=8)`. The keyword arguments are libpq parameters in both drivers, so the call keeps the same shape. Alternative: build a Dagster `DagsterInstance` and touch storage. Rejected: slower, noisier errors, and `dagster definitions validate` already runs right after.

**4. Unified `storage: postgres:` block with explicit `scheme: postgresql+psycopg`.** One block replaces `run_storage`, `schedule_storage` and `event_log_storage`, which dagster-postgres expands to the same three classes. Pinning the scheme means a future SQLAlchemy default change, or someone removing `psycopg[binary]`, fails loudly at startup instead of quietly switching drivers. Alternative: keep the three blocks and only add `scheme` to each. Rejected: triples the edit and keeps the duplication the review pointed out.

**5. Remove `psycopg2-binary` from `[project].dependencies`.** It stays in the environment through `dagster-postgres`'s own requirement, so this does not shrink the install. It just stops the project declaring a dependency it no longer imports. Alternative: keep it as a safety net. Rejected: after decision 3 nothing in the repo imports it, and the transitive pin already covers dagster-postgres.

**6. Test without a database.** `tests/test_dagster_instance.py` reads `dagster.yaml` with PyYAML (already a dagster dependency), takes `storage.postgres`, replaces each `{env: NAME}` value with a dummy string (or int for the port), calls `dagster_postgres.utils.pg_url_from_config`, and asserts:
- the URL starts with `postgresql+psycopg://`
- `sqlalchemy.create_engine(url).dialect.driver == "psycopg"` (creating an engine does not connect).

Alternative: start a real `DagsterInstance` against Docker Postgres. Rejected: needs Docker in `pytest`, which the current test suite avoids.

## Risks / Trade-offs

- [`--wait` needs Compose v2.1+] → Local version is v2.40.3. Note the minimum in the README.
- [`pg_url_from_config` is a dagster-postgres helper, not a documented public API] → It is a small, stable function. If it moves, the test breaks loudly and points at the right place.
- [Unified `storage:` block hides which classes are used] → They are the same three Postgres classes. Verified once by running `scripts/dagster-up.sh` against the existing volume.
- [Loopback bind breaks access from another container or machine] → Dagster runs on the host and connects to `127.0.0.1`, so nothing breaks today. Revert the line if that ever changes.

## Migration Plan

No data migration. After pulling: `uv sync`, then `scripts/dagster-up.sh`. Existing volumes and Dagster history are reused. Rollback is reverting the commit.
