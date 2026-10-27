# dagster-local-infra Specification

## Purpose
How the local Postgres-backed Dagster instance is started, exposed, checked for readiness and configured (driver, storage, code location name). Created by the `harden-dagster-infra` change (T1.5).
## Requirements
### Requirement: Postgres is reachable only from the host
The local Postgres used for Dagster storage SHALL publish its port on the loopback interface (`127.0.0.1`) only.

#### Scenario: Port bound to loopback
- **WHEN** `docker compose config` renders the `postgres` service
- **THEN** its published port has `host_ip: 127.0.0.1` and the target port `5432`

#### Scenario: Custom host port still applies
- **WHEN** `.env` sets `POSTGRES_PUBLISH_PORT=5435`
- **THEN** Postgres is published on `127.0.0.1:5435`

### Requirement: Readiness means accepting TCP connections
The startup script SHALL treat Postgres as ready only once it accepts TCP connections on `localhost` inside the container, using the compose healthcheck as the single readiness rule.

#### Scenario: Fresh volume
- **WHEN** `scripts/dagster-up.sh` runs with no existing Postgres volume
- **THEN** it waits until the healthcheck (`pg_isready -h localhost`) passes, and does not report a credentials error

#### Scenario: Postgres never becomes healthy
- **WHEN** the healthcheck does not pass within the wait timeout
- **THEN** the script exits with a non-zero status and prints how to inspect the container (`docker compose ps` / `docker compose logs postgres`)

#### Scenario: Volume created with other credentials
- **WHEN** Postgres is healthy but rejects `POSTGRES_USER` / `POSTGRES_PASSWORD`
- **THEN** the script exits with a non-zero status and prints the existing `docker compose down -v` hint

### Requirement: Dagster storage uses the psycopg2 driver explicitly
`dagster.yaml` SHALL configure run, schedule and event-log storage through a single `storage: postgres:` block whose connection scheme is `postgresql+psycopg2`.

#### Scenario: Storage URL resolves to psycopg2
- **WHEN** the `storage.postgres` config from `dagster.yaml` is resolved with `pg_url_from_config` (environment values replaced by placeholders)
- **THEN** the URL starts with `postgresql+psycopg2://` and `sqlalchemy.create_engine(url).dialect.driver` is `"psycopg2"`

#### Scenario: Existing volume is reused
- **WHEN** `scripts/dagster-up.sh` runs against a volume created before this change
- **THEN** Dagster starts with the same `run_storage_id` and keeps the previous run history

### Requirement: Host connection check uses the same driver as Dagster
The startup script SHALL check the connection from the host with `psycopg2`, using the same `DAGSTER_POSTGRES_*` values Dagster uses.

#### Scenario: Host check passes
- **WHEN** Postgres is healthy and the credentials are valid
- **THEN** the `psycopg2.connect(...)` check succeeds and the script continues to `dg check defs`

#### Scenario: Host check fails
- **WHEN** the host cannot connect to `127.0.0.1:${DAGSTER_POSTGRES_PORT}`
- **THEN** the script prints the driver error and exits with a non-zero status

### Requirement: The Dagster UI serves under the project's code location name
`scripts/dagster-up.sh` SHALL start Dagster with `dg dev`, and the UI SHALL serve HTTP with the code location registered as `news-politica` (the `code_location_name` in `[tool.dg.project]`).

#### Scenario: UI responds
- **WHEN** `scripts/dagster-up.sh` has printed "Dagster + Postgres ready" and the webserver has started
- **THEN** `http://127.0.0.1:3000` answers with HTTP 200 and the webserver log has no `OperationalError`

#### Scenario: Location name matches
- **WHEN** the UI's GraphQL `workspaceOrError { locationEntries { name } }` is queried
- **THEN** it returns one entry named `news-politica` with `loadStatus` `LOADED`, and the startup log has no "code location name ... does not match" warning

### Requirement: The driver configuration is guarded by a test
The test suite SHALL include a test that needs no running database and fails if `dagster.yaml` stops resolving to the psycopg2 driver.

#### Scenario: Test runs without Docker
- **WHEN** `uv run pytest` runs with Postgres stopped
- **THEN** the storage driver test passes

#### Scenario: Scheme changed to another driver
- **WHEN** `scheme` in `dagster.yaml` is changed to `postgresql+psycopg`
- **THEN** the storage driver test fails

