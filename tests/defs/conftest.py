import logging

from news_politica.defs.assets import (
    catalogo_infobae, catalogo_lanacion, noticias_politica, raw_infobae, raw_lanacion, raw_misionesonline,
)

from ..sources.conftest import client, clock, session  # noqa: F401  (shared fake network)

# The Dagster assets upstream of the sentiment ones, shared by the asset test modules.
UPSTREAM = [catalogo_infobae, catalogo_lanacion, raw_infobae, raw_lanacion, raw_misionesonline, noticias_politica]


def info_logs(instance, result):
    """The INFO messages the assets logged, without Dagster's own events."""
    return [entry.user_message for entry in instance.all_logs(result.run_id)
            if entry.dagster_event is None and entry.level == logging.INFO]


def store(tmp_path, name, frame, partition=None):
    path = tmp_path / name / f"{partition}.parquet" if partition else tmp_path / f"{name}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def metadata(result, name):
    [event] = result.asset_materializations_for_node(name)
    # The IO manager adds the file path.
    return {key: value.value for key, value in event.metadata.items() if key != "path"}
