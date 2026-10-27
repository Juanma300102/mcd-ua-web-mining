## 1. Compose and readiness

- [x] 1.1 In `docker-compose.yaml`, publish the port as `127.0.0.1:${POSTGRES_PUBLISH_PORT:-5434}:5432` and change the healthcheck to `pg_isready -h localhost -U ... -d ...`. Check: `docker compose config` shows `host_ip: 127.0.0.1`.
- [x] 1.2 In `scripts/dagster-up.sh`, replace `docker compose up -d` and the `pg_isready` loop and recheck with `docker compose up -d --wait --wait-timeout 90`. Keep the "port is already allocated" hint and add one pointing at `docker compose ps` / `docker compose logs postgres`. Keep the in-container `psql` credentials check.

## 2. Driver and storage config

- [x] 2.1 Replace the three storage blocks in `src/news_politica/dagster_home/dagster.yaml` with one `storage: postgres: postgres_db:` block (same `env:` values) plus `scheme: postgresql+psycopg`.
- [x] 2.2 In `scripts/dagster-up.sh`, switch the host connection check from `psycopg2.connect` to `psycopg.connect` (same arguments).
- [x] 2.3 Remove `psycopg2-binary` from `[project].dependencies` in `pyproject.toml` and run `uv lock`. Check: `uv sync` still installs it through `dagster-postgres`, and `grep -r psycopg2 src scripts tests` finds nothing.

## 3. Test

- [x] 3.1 Add `tests/test_dagster_instance.py`: load `dagster.yaml`, replace `{env: ...}` values with placeholders, resolve with `pg_url_from_config`, assert the URL starts with `postgresql+psycopg://` and `create_engine(url).dialect.driver == "psycopg"`.
- [x] 3.2 Check the test fails when `scheme` is temporarily set to `postgresql+psycopg2`, then restore it.

## 4. Docs and verification

- [x] 4.1 README: note that Postgres listens on `127.0.0.1` only and that `--wait` needs Docker Compose v2.1+.
- [x] 4.2 Run `uv run pytest` and `uv run dg check defs`.
- [x] 4.3 Run `scripts/dagster-up.sh` against the existing volume (UI opens, previous runs still listed). Then run `docker compose down -v` and start it again to confirm a fresh volume starts with no credentials error. Ask before `down -v`: it deletes the local Dagster history.
- [x] 4.4 Mark T1.5 done in `odd/tasks/news-politica.md` with its commit hash and a Progress line, and commit with a Conventional Commit message.
