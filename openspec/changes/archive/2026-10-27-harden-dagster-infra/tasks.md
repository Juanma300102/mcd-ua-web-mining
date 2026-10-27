## 1. Compose and readiness

- [x] 1.1 In `docker-compose.yaml`, publish the port as `127.0.0.1:${POSTGRES_PUBLISH_PORT:-5434}:5432` and change the healthcheck to `pg_isready -h localhost -U ... -d ...`. Check: `docker compose config` shows `host_ip: 127.0.0.1`.
- [x] 1.2 In `scripts/dagster-up.sh`, replace `docker compose up -d` and the `pg_isready` loop and recheck with `docker compose up -d --wait --wait-timeout 90`. Keep the "port is already allocated" hint and add one pointing at `docker compose ps` / `docker compose logs postgres`. Keep the in-container `psql` credentials check.

## 2. Driver and storage config

- [x] 2.1 Replace the three storage blocks in `src/news_politica/dagster_home/dagster.yaml` with one `storage: postgres: postgres_db:` block (same `env:` values) plus `scheme: postgresql+psycopg2`. (First done with `postgresql+psycopg`; switched after task 5.1.)
- [x] 2.2 Keep the host connection check in `scripts/dagster-up.sh` on `psycopg2.connect` (briefly moved to psycopg 3, reverted with 2.1).
- [x] 2.3 `pyproject.toml`: keep `psycopg2-binary`, remove `psycopg[binary]`, and run `uv lock`. Check: `uv sync` removes psycopg 3, and `grep -r "import psycopg$" src scripts tests` finds nothing.

## 3. Test

- [x] 3.1 Add `tests/test_dagster_instance.py`: load `dagster.yaml`, replace `{env: ...}` values with placeholders, resolve with `pg_url_from_config`, assert the URL starts with `postgresql+psycopg2://` and `create_engine(url).dialect.driver == "psycopg2"`.
- [x] 3.2 Check the test fails when `scheme` is temporarily set to `postgresql+psycopg`, then restore it.

## 4. Docs and verification

- [x] 4.1 README: note that Postgres listens on `127.0.0.1` only and that `--wait` needs Docker Compose v2.1+.
- [x] 4.2 Run `uv run pytest` and `uv run dg check defs`.
- [x] 4.3 Run `scripts/dagster-up.sh` on a fresh volume (healthy, credentials OK on the first try) and again on the same volume (same `run_storage_id`). No volume existed on this machine, so `docker compose down -v` was not needed.
- [x] 4.4 Mark T1.5 done in `odd/tasks/news-politica.md` with its commit hash and a Progress line, and commit with a Conventional Commit message.

## 5. Webserver and code location (found after 4.4)

- [x] 5.1 Confirm the UI over HTTP, not by the "Serving dagster-webserver" log line. Finding: with psycopg 3 the webserver fails `get_run_storage_id` with "the connection is closed" and never listens. With psycopg2 it answers 200. Led to the switch in 2.1–2.3.
- [x] 5.2 Set `code_location_name = "news-politica"` under `[tool.dg.project]`, and in `scripts/dagster-up.sh` replace `dagster definitions validate -m ...` / `dagster dev -m ...` with `dg check defs` / `dg dev`.
- [x] 5.3 Verify: `scripts/dagster-up.sh` → `http://127.0.0.1:3000` returns 200, GraphQL `locationEntries` is `news-politica` / `LOADED`, and the log has no location-name, supersession or `OperationalError` lines.
