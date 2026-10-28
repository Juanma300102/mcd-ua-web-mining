"""Sentiment assets: `sentimiento_noticias` scores every note of `noticias_politica`.

The Dagster layer stays thin. The scoring logic is in `news_politica.sentiment`, and
the models (torch, Ollama) are built on demand by the `sentiment_models` resource, so
loading these definitions never imports torch.
"""

import dagster as dg
import pandas as pd

from news_politica.sentiment.classifiers import ModelUnavailable, SentimentModels
from news_politica.sentiment.scoring import SCORE_COLUMNS, score_notes

MODELO_FINAL = "robertuito"  # updated with the decision in docs/decision-sentimiento.md (task 7.3)


class ScoringConfig(dg.Config):
    modelos: list[str] = [MODELO_FINAL]


@dg.asset
def sentimiento_noticias(
    context,
    config: ScoringConfig,
    sentiment_models: dg.ResourceParam[SentimentModels],
    noticias_politica: pd.DataFrame,
) -> pd.DataFrame:
    """Probabilities, label and `score = prob_pos - prob_neg` per note and model, in long format."""
    total = len(noticias_politica)
    context.log.info(f"scoring {total} notes with {', '.join(config.modelos)}")
    frames = []
    for name in config.modelos:
        try:
            classifier = sentiment_models.load(name)
        except ModelUnavailable as error:
            # Retrying does not install a library or start a server.
            raise dg.Failure(f"{name} is not available: {error}", allow_retries=False) from error
        except ValueError as error:
            raise dg.Failure(str(error), allow_retries=False) from error
        frames.append(score_notes(noticias_politica, classifier, log=context.log))
    scores = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SCORE_COLUMNS)
    per_model = scores["modelo"].value_counts().to_dict()
    labels = {
        modelo: frame["label"].value_counts().to_dict() for modelo, frame in scores.groupby("modelo", sort=False)
    }
    unparsed = int(scores["label"].isna().sum())
    context.log.info(f"{len(scores)} rows scored ({per_model}), {unparsed} unparsed")
    context.add_output_metadata({
        "rows": len(scores),
        "rows_per_modelo": dg.MetadataValue.json(per_model),
        "labels": dg.MetadataValue.json(labels),
        "unparsed": unparsed,
    })
    return scores
