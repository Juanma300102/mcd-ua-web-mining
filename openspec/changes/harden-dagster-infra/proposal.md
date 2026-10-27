## Why

The review of Phase 1 (`69c65fa..d35aece`) left four warnings on the local Dagster infra: Postgres is published on all host interfaces with default credentials, the first start on a fresh volume can fail with a false "wrong credentials" error, and the host connection check tests psycopg2 while Dagster actually connects through psycopg 3. Fixing them now, before Phase 2 adds real assets and a long backfill, is cheap and keeps the startup script trustworthy for both team members. This is T1.5 in `odd/tasks/news-politica.md`.

## What Changes

- Publish the Postgres port on `127.0.0.1` only, instead of every host interface.
- Make readiness mean "accepts TCP connections": the compose healthcheck runs `pg_isready -h localhost`, and `scripts/dagster-up.sh` waits with `docker compose up -d --wait` instead of its own `pg_isready` loop (removes the duplicated readiness check).
- Switch the host connection check in `scripts/dagster-up.sh` from `psycopg2` to `psycopg` (3), the driver Dagster uses.
- Collapse the three storage blocks in `dagster.yaml` into one `storage: postgres:` block and pin `scheme: postgresql+psycopg`, so the driver is explicit rather than SQLAlchemy's default.
- Drop `psycopg2-binary` from the project's direct dependencies (still installed transitively by `dagster-postgres`, but nothing in this repo uses it after the change).
- Add a test, with no database needed, that loads `dagster.yaml` and asserts the storage URL resolves to the psycopg 3 SQLAlchemy driver.

## Capabilities

### New Capabilities
- `dagster-local-infra`: how the local Postgres-backed Dagster instance is started, exposed, checked for readiness and configured (driver, storage), and the test that guards that configuration.

### Modified Capabilities
<!-- None: there are no existing specs in openspec/specs/. -->

## Impact

- Files: `docker-compose.yaml`, `scripts/dagster-up.sh`, `src/news_politica/dagster_home/dagster.yaml`, `pyproject.toml`, `uv.lock`, new `tests/test_dagster_instance.py`, `README.md` (port binding note), `odd/tasks/news-politica.md` (T1.5 status).
- Requires Docker Compose v2.1+ for `--wait` (local version is v2.40.3).
- No change to Dagster definitions or data. Existing Postgres volumes keep working; Dagster's tables are the same with the unified storage block.
- Postgres is no longer reachable from other machines on the LAN. Nobody relies on that today.
