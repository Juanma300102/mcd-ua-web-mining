## Context

Phase 1 left a local stack: `docker-compose.yaml` runs `postgres:16-alpine`, `scripts/dagster-up.sh` starts it, checks it and runs Dagster, and `src/news_politica/dagster_home/dagster.yaml` points run, schedule and event-log storage at it.

Findings from reading and running the installed packages (dagster 1.13.27, dagster-postgres 0.29.27, SQLAlchemy 2.1.6):

- `dagster_postgres` never imports a driver itself. Every connection goes through `sqlalchemy.create_engine(pg_url_from_config(...))`, and with SQLAlchemy 2.1 a bare `postgresql://` URL resolves to the `psycopg` (3) dialect. That is why T1.2 had to add `psycopg[binary]`.
- With psycopg 3, `dagster-webserver` crashes on startup. `log_action` → `run_storage.get_run_storage_id()` fails with `psycopg.OperationalError: the connection is closed`, after the "Serving dagster-webserver" line is already printed, so nothing listens on the port. The same instance works in a plain Python process, and the webserver serves HTTP 200 with `postgresql+psycopg2`. Root cause not investigated. It is specific to the webserver process, not to the storage config.
- The `postgres_db` config shape accepts `scheme` (default `"postgresql"`), and the instance config accepts a unified `storage: postgres:` block.
- The official Postgres image initialises a fresh volume with a temporary server that listens only on the Unix socket, then restarts with TCP enabled. `pg_isready` without `-h` uses the socket, so it reports ready during that window, and the script's next step (`psql -h localhost`) fails and prints the "volume has another password" message.
- `dagster dev -m news_politica.definitions` registers the location as `news_politica.definitions`, while the component tree takes `code_location_name` from `[tool.dg.project]` or, if unset, the folder name (`mcd-ua-web-mining`). `dagster dev` cannot rename the location, and it prints that it is superseded by `dg dev`.

## Goals / Non-Goals

**Goals:**
- Postgres reachable only from the host machine.
- "Ready" means ready over TCP, checked in one place.
- Dagster storage pinned to a driver the webserver works with, and a test that fails if that pin changes.
- A shorter `dagster.yaml` with no repeated blocks.
- The UI actually serves, and starts with no code location warnings.

**Non-Goals:**
- Finding the root cause of the psycopg 3 failure in the webserver.
- Changing the Postgres image, credentials scheme or port defaults.
- Moving the dataset into Postgres (still an open decision in the plan).
- CI setup.

## Decisions

**1. Bind to `127.0.0.1` in compose.** `ports: "127.0.0.1:${POSTGRES_PUBLISH_PORT:-5434}:5432"`. Alternative: make the bind address an env var. Rejected: no one needs LAN access, and one more knob adds nothing.

**2. Readiness via the compose healthcheck plus `docker compose up -d --wait`.** The healthcheck becomes `pg_isready -h localhost -U ... -d ...`, and the script calls `docker compose up -d --wait --wait-timeout 90` (matching the old 90 s loop). The manual loop and the second `pg_isready` call are removed. Alternative: keep the loop and add `-h localhost`. Rejected: the readiness rule would live in two places that can drift. On failure the script keeps the "port is already allocated" hint and adds `docker compose ps` / `docker compose logs postgres`. The in-container `psql ... select 1` check stays, because `pg_isready` does not check the password.

**3. Pin `scheme: postgresql+psycopg2`.** This is the driver the webserver works with, and pinning it also makes the driver explicit instead of depending on SQLAlchemy's default. Alternative: pin `postgresql+psycopg` (the first version of this change). Rejected after the webserver failure above. Alternative: debug psycopg 3 in the webserver. Out of scope; it can be revisited when upgrading Dagster.

**4. Unified `storage: postgres:` block.** One block replaces `run_storage`, `schedule_storage` and `event_log_storage`, which dagster-postgres expands to the same three classes. Alternative: keep the three blocks with `scheme` in each. Rejected: triples the edit and keeps the duplication the review pointed out.

**5. Dependencies: keep `psycopg2-binary`, drop `psycopg[binary]`.** `psycopg2-binary` is what the pinned scheme imports, so it stays a direct dependency even though `dagster-postgres` also declares it. Nothing imports psycopg 3 any more.

**6. Host check with psycopg2.** The check in `dagster-up.sh` keeps `psycopg2.connect(...)`, which is now by design the same driver as the storage.

**7. Test without a database.** `tests/test_dagster_instance.py` reads `dagster.yaml`, replaces each `{env: NAME}` value with a placeholder, calls `dagster_postgres.utils.pg_url_from_config`, and asserts that the URL starts with `postgresql+psycopg2://` and that `sqlalchemy.create_engine(url).dialect.driver == "psycopg2"` (creating an engine does not connect). Alternative: start the webserver against Docker in `pytest`. Rejected: needs Docker in the test suite.

**8. `dg dev` and an explicit `code_location_name`.** `[tool.dg.project]` sets `code_location_name = "news-politica"`, and the script runs `uv run dg check defs` and `exec uv run dg dev`. `dg dev` registers the location under that name, so it matches the component tree and the warning goes away. Alternative: set `code_location_name = "news_politica.definitions"` and keep `dagster dev`. Rejected: an awkward name, plus a command Dagster marks as superseded.

## Risks / Trade-offs

- [psycopg2 is in maintenance mode, and a future Dagster may drop it] → The test pins the driver, so a dependency change that breaks it shows up in `pytest`. Revisit psycopg 3 when upgrading Dagster.
- [`--wait` needs Compose v2.1+] → Local version is v2.40.3. Noted in the README.
- [`pg_url_from_config` is a dagster-postgres helper, not a documented public API] → A small, stable function. If it moves, the test breaks loudly.
- [The "Serving dagster-webserver" log line does not prove the UI is up] → Verification checks the UI over HTTP (`curl` → 200, GraphQL `locationEntries`).
- [Loopback bind breaks access from another container or machine] → Dagster runs on the host and connects to `127.0.0.1`, so nothing breaks today.

## Migration Plan

No data migration. After pulling: `uv sync`, then `scripts/dagster-up.sh`. Existing volumes and Dagster history are reused. Rollback is reverting the commits.
