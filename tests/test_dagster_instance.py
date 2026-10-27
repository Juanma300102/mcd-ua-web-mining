from pathlib import Path

import sqlalchemy as sa
import yaml
from dagster_postgres.utils import pg_url_from_config

DAGSTER_YAML = Path(__file__).parents[1] / "src/news_politica/dagster_home/dagster.yaml"


def _placeholders(value):
    # Replace {env: NAME} with a dummy value so the URL resolves without a database.
    if isinstance(value, dict):
        if set(value) == {"env"}:
            return "5432" if value["env"].endswith("_PORT") else "placeholder"
        return {key: _placeholders(item) for key, item in value.items()}
    return value


def test_storage_uses_psycopg3_driver():
    config = yaml.safe_load(DAGSTER_YAML.read_text())["storage"]["postgres"]
    url = pg_url_from_config(_placeholders(config))

    assert url.startswith("postgresql+psycopg://")
    # create_engine does not connect, it only resolves the dialect and driver.
    assert sa.create_engine(url).dialect.driver == "psycopg"
