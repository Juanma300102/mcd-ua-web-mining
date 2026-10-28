"""Sentiment assets: `sentimiento_noticias` scores every note of `noticias_politica`;
`evolucion_tono` aggregates those scores by week and outlet.

The Dagster layer stays thin. The scoring logic is in `news_politica.sentiment`, and
the models (torch, Ollama) are built on demand by the `sentiment_models` resource, so
loading these definitions never imports torch.
"""

import dagster as dg
import pandas as pd
from pydantic import field_validator

from news_politica.sentiment.classifiers import ModelUnavailable, SentimentModels, UnknownModel
from news_politica.sentiment.scoring import SCORE_COLUMNS, score_notes
from news_politica.sentiment.tone import tone_exclusions, weekly_tone

MODELO_FINAL = "robertuito"  # updated with the decision in docs/decision-sentimiento.md (task 7.3)


class ScoringConfig(dg.Config):
    modelos: list[str] = [MODELO_FINAL]

    @field_validator("modelos")
    @classmethod
    def _unique(cls, names: list[str]) -> list[str]:
        """Keep the first occurrence so the output stays one row per (id, modelo)."""
        return list(dict.fromkeys(names))


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
        except UnknownModel as error:
            # A typo in the `modelos` config; only this error, so unrelated ValueErrors still surface.
            raise dg.Failure(str(error), allow_retries=False) from error
        try:
            frames.append(score_notes(noticias_politica, classifier, log=context.log))
        except ModelUnavailable as error:
            # Ollama can go away mid-run (stopped, OOM); retrying the whole run would not bring it back.
            raise dg.Failure(f"{name} became unavailable while scoring: {error}", allow_retries=False) from error
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


@dg.asset
def evolucion_tono(
    context,
    sentimiento_noticias: pd.DataFrame,
    noticias_politica: pd.DataFrame,
) -> pd.DataFrame:
    """Weekly tone per model and outlet: `n`, mean score with its 95 % interval, label shares, bajada coverage.

    Live notes, unparsed notes, notes without a date and scores without a note are excluded and counted
    in the summary line and the `excluidas` metadata; the weeks are ISO weeks in ART keyed by their Monday.
    """
    context.log.info(f"computing weekly tone from {len(sentimiento_noticias)} scored rows")
    weekly = weekly_tone(sentimiento_noticias, noticias_politica)
    models = weekly["modelo"].nunique()
    outlets = weekly["medio"].nunique()
    dropped = tone_exclusions(sentimiento_noticias, noticias_politica)
    skipped = ", ".join(f"{count} {reason}" for reason, count in dropped.items())
    context.log.info(f"{len(weekly)} weekly rows ({models} models, {outlets} outlets); dropped {skipped}")
    context.add_output_metadata({"rows": len(weekly), "excluidas": dg.MetadataValue.json(dropped)})
    return weekly
