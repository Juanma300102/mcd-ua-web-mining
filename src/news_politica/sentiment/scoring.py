"""Score notes with a classifier and build the long-format frame."""

from __future__ import annotations

import math

import pandas as pd

from news_politica.sentiment.classifiers import Classifier
from news_politica.sentiment.text import analysis_text

BATCH_SIZE = 32
LOG_EVERY = 10  # progress lines every LOG_EVERY batches, to keep the run log short
LABELS = ("pos", "neu", "neg")  # same order as the probabilities
SCORE_COLUMNS = ["id", "modelo", "fuente_texto", "prob_pos", "prob_neu", "prob_neg", "label", "score"]


def _label(probs) -> str | None:
    if any(math.isnan(p) for p in probs):
        return None
    return LABELS[max(range(3), key=lambda i: probs[i])]


def score_notes(
    notes: pd.DataFrame,
    classifier: Classifier,
    batch_size: int = BATCH_SIZE,
    log=None,
) -> pd.DataFrame:
    """One row per note: probabilities, argmax `label` and `score = prob_pos - prob_neg`.

    The model input comes from `analysis_text`. Unparseable outputs (NaN
    probabilities) keep `label` None and a NaN score, and are counted in the
    summary line. Progress is logged every `LOG_EVERY` batches.
    """
    texts = [
        analysis_text(t, b, c)
        for t, b, c in zip(notes["titulo"], notes["bajada"], notes["cuerpo"], strict=True)
    ]
    total = len(texts)
    probs: list[tuple[float, float, float]] = []
    for batch_number, start in enumerate(range(0, total, batch_size), start=1):
        batch = [text for text, _ in texts[start : start + batch_size]]
        result = classifier.predict(batch)
        if len(result) != len(batch):
            raise ValueError(f"{classifier.name} returned {len(result)} outputs for {len(batch)} texts")
        probs.extend(result)
        if log and batch_number % LOG_EVERY == 0:
            log.info(f"{classifier.name}: {len(probs)}/{total} notes scored")
    frame = pd.DataFrame(
        {
            "id": notes["id"].to_numpy(),
            "modelo": classifier.name,
            "fuente_texto": [source for _, source in texts],
            "prob_pos": [p[0] for p in probs],
            "prob_neu": [p[1] for p in probs],
            "prob_neg": [p[2] for p in probs],
            "label": pd.Series([_label(p) for p in probs], dtype=object),
        }
    )
    frame["score"] = frame["prob_pos"] - frame["prob_neg"]
    frame = frame[SCORE_COLUMNS]
    if log:
        counts = frame["label"].value_counts()
        unparsed = int(frame["label"].isna().sum())
        log.info(
            f"{classifier.name}: {total} notes scored ({counts.get('neg', 0)} neg, "
            f"{counts.get('neu', 0)} neu, {counts.get('pos', 0)} pos, {unparsed} unparsed)"
        )
    return frame
