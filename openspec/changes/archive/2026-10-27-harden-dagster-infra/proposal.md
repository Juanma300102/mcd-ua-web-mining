## Why

The review of Phase 1 (`69c65fa..d35aece`) left four warnings on the local Dagster infra: Postgres is published on all host interfaces with default credentials, the first start on a fresh volume can fail with a false "wrong credentials" error, and the host connection check tests a different driver than the one Dagster's storage resolves to. While fixing them we found a bigger problem: with SQLAlchemy 2.1's default driver (psycopg 3), `dagster-webserver` crashes on its first storage query, so the UI never serves even though the log prints "Serving dagster-webserver". Fixing this now, before Phase 2 adds real assets and a long backfill, keeps the startup script trustworthy for both team members. This is T1.5 in `odd/tasks/news-politica.md`.

## What Changes

- Publish the Postgres port on `127.0.0.1` only, instead of every host interface.
- Make readiness mean "accepts TCP connections": the compose healthcheck runs `pg_isready -h localhost`, and `scripts/dagster-up.sh` waits with `docker compose up -d --wait` instead of its own `pg_isready` loop (removes the duplicated readiness check).
- Collapse the three storage blocks in `dagster.yaml` into one `storage: postgres:` block and pin `scheme: postgresql+psycopg2`, the driver the webserver works with.
- Keep the host connection check on `psycopg2`, now explicitly the same driver as Dagster's storage.
- Drop `psycopg[binary]` from the dependencies (added in T1.2 only because SQLAlchemy 2.1 picked psycopg 3 for a bare `postgresql://` URL); keep `psycopg2-binary` as a direct dependency.
- Add a test, with no database needed, that loads `dagster.yaml` and asserts the storage URL resolves to the psycopg2 SQLAlchemy driver.
- Start Dagster with `dg dev` and validate with `dg check defs` (`dagster dev` is superseded), and set `code_location_name = "news-politica"` under `[tool.dg.project]`, which removes the code location name mismatch warning.

## Capabilities

### New Capabilities
- `dagster-local-infra`: how the local Postgres-backed Dagster instance is started, exposed, checked for readiness and configured (driver, storage, code location name), and the test that guards the driver configuration.

### Modified Capabilities
<!-- None: there are no existing specs in openspec/specs/. -->

## Impact

- Files: `docker-compose.yaml`, `scripts/dagster-up.sh`, `src/news_politica/dagster_home/dagster.yaml`, `pyproject.toml`, `uv.lock`, new `tests/test_dagster_instance.py`, `README.md`, `odd/tasks/news-politica.md` (T1.5 status).
- Requires Docker Compose v2.1+ for `--wait` (local version is v2.40.3).
- No change to Dagster definitions or data. Existing Postgres volumes keep working; Dagster's tables are the same with the unified storage block.
- Postgres is no longer reachable from other machines on the LAN. Nobody relies on that today.
- The code location shows as `news-politica` in the UI (was `news_politica.definitions`). There is no run history tied to the old name yet.
