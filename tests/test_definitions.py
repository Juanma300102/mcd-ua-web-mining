import dagster as dg

from news_politica.definitions import defs


def test_definitions_load():
    assert isinstance(defs(), dg.Definitions)
