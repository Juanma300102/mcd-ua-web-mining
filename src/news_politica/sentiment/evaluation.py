"""Compare model labels with the human labels: accuracy, macro F1 and confusion matrices.

Plain pandas (no scikit-learn). `descartar` labels are excluded before anything is
counted. A kept note whose model output was unparseable (`label` None) stays in `n`
and counts as a miss: it lowers accuracy and the recall of its true class, and shows
up in the confusion matrix under `SIN_RESPUESTA`. Any other prediction outside
`CLASSES` is an error, so every confusion matrix adds up to its group's `n`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import pandas as pd

CLASSES = ("pos", "neu", "neg")
DISCARD = "descartar"
SIN_RESPUESTA = "sin_respuesta"
METRIC_COLUMNS = ["n", "accuracy", "macro_f1", *(f"f1_{c}" for c in CLASSES)]


def _f1(tp: int, fp: int, fn: int) -> float:
    """F1 of one class; NaN when the class has no support and no predictions."""
    if tp + fp + fn == 0:
        return float("nan")
    return 2 * tp / (2 * tp + fp + fn)


def _metrics(true: pd.Series, pred: pd.Series) -> dict[str, float]:
    f1 = {
        c: _f1(int(((true == c) & (pred == c)).sum()), int(((true != c) & (pred == c)).sum()),
               int(((true == c) & (pred != c)).sum()))
        for c in CLASSES
    }
    present = [v for v in f1.values() if not math.isnan(v)]  # macro average over classes that occur at all
    return {
        "n": len(true),
        "accuracy": float((true == pred).mean()),
        "macro_f1": sum(present) / len(present) if present else float("nan"),
        **{f"f1_{c}": v for c, v in f1.items()},
    }


def _confusion(true: pd.Series, pred: pd.Series) -> pd.DataFrame:
    shown = pred.fillna(SIN_RESPUESTA)
    cells = pd.crosstab(true, shown).reindex(index=list(CLASSES), columns=[*CLASSES, SIN_RESPUESTA], fill_value=0)
    cells = cells.fillna(0).astype(int)
    out = cells.stack().rename("n").reset_index()
    out.columns = ["etiqueta", "prediccion", "n"]
    return out


def evaluate(
    labels: pd.DataFrame, scores: pd.DataFrame, by: Sequence[str] = ("modelo",)
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Metrics and confusion matrix per group of `by`.

    `labels` has `id, etiqueta` (the output of `read_labels`; ids must be unique); `scores` is the long frame of
    `score_notes` plus any grouping column in `by` that it lacks (e.g. `medio`). Only ids present in
    both are compared, and `descartar` rows are dropped first. Duplicated ids in `labels`, duplicated
    `(id, modelo)` in `scores`, missing grouping values and predictions outside the classes raise `ValueError`.

    Returns `(metrics, confusion)`. `metrics` has the `by` columns, `n`, `accuracy`, `macro_f1`
    and `f1_pos`, `f1_neu`, `f1_neg`. `confusion` is long: the `by` columns, the human
    `etiqueta`, the model `prediccion` (or `sin_respuesta`) and the count `n`.
    """
    by = list(by)
    missing = [c for c in ["id", "label", *by] if c not in scores.columns]
    if missing:
        raise ValueError(f"scores lacks the columns {missing}")
    if labels["id"].duplicated().any():
        raise ValueError(f"duplicated ids in labels: {labels.loc[labels['id'].duplicated(), 'id'].head(3).tolist()}")
    per_model = ["id", "modelo"] if "modelo" in scores.columns else ["id"]
    repeated = scores.duplicated(per_model)
    if repeated.any():
        raise ValueError(f"duplicated {tuple(per_model)} in scores, e.g. {scores.loc[repeated, 'id'].head(3).tolist()}")
    kept = labels.loc[labels["etiqueta"] != DISCARD, ["id", "etiqueta"]]
    unknown = sorted(set(kept["etiqueta"]) - set(CLASSES))
    if unknown:
        raise ValueError(f"unknown labels {unknown}; expected {list(CLASSES)} or {DISCARD!r}")
    joined = kept.merge(scores[["id", "label", *by]], on="id", how="inner")
    # A missing group key (e.g. a note without outlet) is a data error, not a group: pandas would drop it silently.
    absent = [c for c in by if joined[c].isna().any()]
    if absent:
        raise ValueError(f"missing values in the grouping columns {absent}")
    stray = sorted(set(joined["label"].dropna()) - set(CLASSES))
    if stray:
        raise ValueError(f"unknown predictions {stray}; expected {list(CLASSES)} or missing for unparsed")
    metric_rows, confusion_frames = [], []
    for key, group in joined.groupby(by, sort=True):
        key = key if isinstance(key, tuple) else (key,)
        group_key = dict(zip(by, key, strict=True))
        metric_rows.append({**group_key, **_metrics(group["etiqueta"], group["label"])})
        matrix = _confusion(group["etiqueta"], group["label"])
        for position, (column, value) in enumerate(group_key.items()):
            matrix.insert(position, column, value)
        confusion_frames.append(matrix)
    metrics = pd.DataFrame(metric_rows, columns=[*by, *METRIC_COLUMNS])
    confusion_columns = [*by, "etiqueta", "prediccion", "n"]
    confusion = pd.concat(confusion_frames, ignore_index=True) if confusion_frames else pd.DataFrame(columns=confusion_columns)
    return metrics, confusion
