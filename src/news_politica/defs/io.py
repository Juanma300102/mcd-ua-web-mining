"""Parquet storage under data/ for every asset, and the resources: HTTP client and sentiment models."""

import os
from pathlib import Path

import dagster as dg
import pandas as pd
from upath import UPath

from news_politica.sentiment.classifiers import SentimentModels
from news_politica.sources.http import PoliteClient

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parents[3] / "data"))


class ParquetIOManager(dg.UPathIOManager):
    """data/<asset>.parquet, or data/<asset>/<partition>.parquet for partitioned assets."""

    extension = ".parquet"

    def dump_to_path(self, context, obj: pd.DataFrame, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        obj.to_parquet(path, index=False)

    def load_from_path(self, context, path) -> pd.DataFrame:
        return pd.read_parquet(path)


@dg.definitions
def resources():
    # Each run process loads the definitions again, so each run gets its own PoliteClient.
    return dg.Definitions(resources={
        "io_manager": ParquetIOManager(base_path=UPath(DATA_DIR)),
        "client": PoliteClient(),
        "sentiment_models": SentimentModels(),  # builds classifiers on demand; no torch import here
    })
