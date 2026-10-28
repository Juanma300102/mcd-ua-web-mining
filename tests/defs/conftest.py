import logging

from ..sources.conftest import client, clock, session  # noqa: F401  (shared fake network)


def info_logs(instance, result):
    """The INFO messages the assets logged, without Dagster's own events."""
    return [entry.user_message for entry in instance.all_logs(result.run_id)
            if entry.dagster_event is None and entry.level == logging.INFO]
