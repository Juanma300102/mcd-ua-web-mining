"""Weekly tone per outlet and before/after comparison around milestones.

Pure pandas and scipy; no Dagster, no models. Weeks are ISO weeks in Argentina time
(ART), keyed by their Monday at 00:00 ART. Live notes and notes without a score
(unparsed model output) are excluded everywhere. Scores of different models do not
share a scale, so every aggregate is kept per `modelo`.
"""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd
from scipy import stats

from news_politica.sentiment.labeling import as_bool
from news_politica.sources.arc import CUTOFF, START
from news_politica.sources.text import ART

N_MIN = 10  # fewest notes on a side of a milestone window to report its mean and share
WINDOW_DAYS = 14
CONFIDENCE = 0.95
# Dataset period: 2023-12-10 (first sitemap day) to the 2026-09-30 cut-off, defined in
# `sources.arc` and used by `defs/assets.py` (see docs/def.md). The end is exclusive.
DATASET_START = datetime(START.year, START.month, START.day, tzinfo=ART)
DATASET_END = datetime(CUTOFF.year, CUTOFF.month, CUTOFF.day, tzinfo=ART)

WEEKLY_COLUMNS = [
    "modelo", "medio", "semana", "n", "score_medio", "ic_inf", "ic_sup",
    "prop_pos", "prop_neu", "prop_neg", "prop_bajada",
]
MILESTONE_COLUMNS = [
    "modelo", "hito", "alcance", "fecha", "medio", "n_antes", "n_despues", "score_antes", "score_despues",
    "diferencia", "ic_inf", "ic_sup", "prop_neg_antes", "prop_neg_despues", "dias_antes", "dias_despues",
    "truncada", "insuficiente",
]


def _eligible_with_drops(scores: pd.DataFrame, notes: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Eligible scores plus how many score rows each rule dropped (first rule that applies wins).

    Rules, in order: `sin_nota` (the id is not in `notes`), `en_vivo` (live note), `score_nan`
    (unparsed model output) and `sin_fecha` (null publication date).
    """
    for name, frame, needed in (
        ("scores", scores, ["id", "modelo", "fuente_texto", "label", "score"]),
        ("notes", notes, ["id", "medio", "fecha_publicacion", "es_en_vivo"]),
    ):
        missing = [c for c in needed if c not in frame.columns]
        if missing:
            raise ValueError(f"{name} lacks the columns {missing}")
    if scores.duplicated(["id", "modelo"]).any():
        dup = scores.loc[scores.duplicated(["id", "modelo"]), ["id", "modelo"]].head(3)
        raise ValueError(f"duplicated (id, modelo) score rows: {list(dup.itertuples(index=False, name=None))}")
    if notes["id"].duplicated().any():
        raise ValueError(f"duplicated note ids: {notes.loc[notes['id'].duplicated(), 'id'].head(3).tolist()}")
    info = notes[["id", "medio", "fecha_publicacion"]].assign(en_vivo=as_bool(notes["es_en_vivo"]))
    joined = scores[["id", "modelo", "fuente_texto", "label", "score"]].merge(info, on="id", how="left", indicator=True)
    dropped = {"sin_nota": int((joined["_merge"] == "left_only").sum())}
    joined = joined[joined["_merge"] == "both"].drop(columns="_merge")
    joined["en_vivo"] = joined["en_vivo"].astype(bool)  # the left merge made it object
    dropped["en_vivo"] = int(joined["en_vivo"].sum())
    joined = joined[~joined["en_vivo"]]
    dropped["score_nan"] = int(joined["score"].isna().sum())
    joined = joined[joined["score"].notna()].copy()
    joined["momento"] = pd.to_datetime(joined["fecha_publicacion"], utc=True).dt.tz_convert(ART)
    dropped["sin_fecha"] = int(joined["momento"].isna().sum())
    joined = joined[joined["momento"].notna()]
    return joined.drop(columns=["fecha_publicacion", "en_vivo"]), dropped


def _eligible(scores: pd.DataFrame, notes: pd.DataFrame) -> pd.DataFrame:
    """Scores joined with outlet and ART publication time, without live notes, NaN scores or null dates."""
    return _eligible_with_drops(scores, notes)[0]


def tone_exclusions(scores: pd.DataFrame, notes: pd.DataFrame) -> dict[str, int]:
    """Score rows that `weekly_tone` leaves out, by reason: `sin_nota`, `en_vivo`, `score_nan`, `sin_fecha`."""
    return _eligible_with_drops(scores, notes)[1]


def _half_width(sd: pd.Series, n: pd.Series) -> pd.Series:
    """Half-width of the Student t interval of a mean; NaN below two notes (undefined)."""
    crit = stats.t.ppf(1 - (1 - CONFIDENCE) / 2, (n - 1).clip(lower=1))
    return (crit * sd / np.sqrt(n)).where(n >= 2)


def weekly_tone(scores: pd.DataFrame, notes: pd.DataFrame) -> pd.DataFrame:
    """One row per `(modelo, medio, semana)`: `n`, mean score with its 95 % t interval, label shares.

    `scores` is the long frame of `score_notes`; `notes` brings `medio`, `fecha_publicacion` and
    `es_en_vivo`. `semana` is the Monday 00:00 ART of the ISO week, so a note published on Sunday
    23:30 ART belongs to that Sunday's week even though it is already Monday in UTC. A week with one
    note has `n` 1, its mean and an empty interval. `prop_bajada` is the share of notes whose
    analysis text came from the bajada (the coverage to show next to the series).
    """
    data = _eligible(scores, notes)
    if data.empty:
        return pd.DataFrame(columns=WEEKLY_COLUMNS)
    day = data["momento"].dt.normalize()
    data["semana"] = day - pd.to_timedelta(data["momento"].dt.day_of_week, unit="D")
    for label in ("pos", "neu", "neg"):
        data[f"prop_{label}"] = (data["label"] == label).astype(float)
    data["prop_bajada"] = (data["fuente_texto"] == "bajada").astype(float)
    weekly = data.groupby(["modelo", "medio", "semana"], sort=True).agg(
        n=("score", "size"),
        score_medio=("score", "mean"),
        sd=("score", "std"),
        prop_pos=("prop_pos", "mean"),
        prop_neu=("prop_neu", "mean"),
        prop_neg=("prop_neg", "mean"),
        prop_bajada=("prop_bajada", "mean"),
    ).reset_index()
    half = _half_width(weekly["sd"], weekly["n"])
    weekly["ic_inf"] = weekly["score_medio"] - half
    weekly["ic_sup"] = weekly["score_medio"] + half
    return weekly[WEEKLY_COLUMNS]


def _milestone_date(value, hito: str) -> pd.Timestamp | None:
    """The milestone day at 00:00 ART, or None when the date is still empty."""
    if value is None or (isinstance(value, float) and math.isnan(value)) or str(value).strip() == "":
        return None
    try:
        stamp = pd.Timestamp(str(value).strip())
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert(ART).tz_localize(None)
        return stamp.normalize().tz_localize(ART)
    except ValueError as exc:
        raise ValueError(f"milestone {hito!r}: invalid date {value!r}") from exc


def _welch(before: np.ndarray, after: np.ndarray) -> tuple[float, float, float]:
    """Difference of means (after - before) and its 95 % Welch interval."""
    diff = float(after.mean() - before.mean())
    var_b, var_a = before.var(ddof=1) / len(before), after.var(ddof=1) / len(after)
    se = math.sqrt(var_b + var_a)
    if se == 0:
        return diff, diff, diff
    df = (var_b + var_a) ** 2 / (var_b**2 / (len(before) - 1) + var_a**2 / (len(after) - 1))
    half = float(stats.t.ppf(1 - (1 - CONFIDENCE) / 2, df)) * se
    return diff, diff - half, diff + half


def compare_milestones(
    scores: pd.DataFrame,
    notes: pd.DataFrame,
    milestones: pd.DataFrame,
    days: int = WINDOW_DAYS,
    n_min: int = N_MIN,
) -> pd.DataFrame:
    """Compare equal windows before and after each milestone, per `(modelo, hito, medio)`.

    `milestones` has `hito, fecha, alcance` (extra columns are ignored); `fecha` is the first ART day
    on which coverage can appear. A row with an empty `fecha` is left out. The windows are
    `[fecha - days, fecha)` and `[fecha, fecha + days)` at 00:00 ART, clipped to the dataset period
    `[DATASET_START, DATASET_END)`: `dias_antes` / `dias_despues` are the clipped lengths and
    `truncada` is true when either is shorter than `days`. The milestone day counts as "after".

    A side with fewer than `n_min` notes reports `n` but no mean or share, and `insuficiente` is
    true when either side is. The difference and its Welch interval need both sides.
    """
    for column in ("hito", "fecha", "alcance"):
        if column not in milestones.columns:
            raise ValueError(f"milestones lacks the column {column!r}")
    if n_min < 2:
        raise ValueError(f"n_min must be at least 2 to estimate a variance, got {n_min}")
    data = _eligible(scores, notes)
    rows = []
    for milestone in milestones.itertuples(index=False):
        day = _milestone_date(milestone.fecha, milestone.hito)
        if day is None:
            continue
        start = max(day - pd.Timedelta(days=days), pd.Timestamp(DATASET_START))
        end = min(day + pd.Timedelta(days=days), pd.Timestamp(DATASET_END))
        days_before = max((day - start).days, 0)
        days_after = max((end - day).days, 0)
        for (modelo, medio), group in data.groupby(["modelo", "medio"], sort=True):
            before = group[(group["momento"] >= start) & (group["momento"] < day)]
            after = group[(group["momento"] >= day) & (group["momento"] < end)]
            enough = {"antes": len(before) >= n_min, "despues": len(after) >= n_min}
            diff = low = high = math.nan
            if all(enough.values()):
                diff, low, high = _welch(before["score"].to_numpy(), after["score"].to_numpy())
            rows.append({
                "modelo": modelo,
                "hito": milestone.hito,
                "alcance": milestone.alcance,
                "fecha": day.date(),
                "medio": medio,
                "n_antes": len(before),
                "n_despues": len(after),
                "score_antes": before["score"].mean() if enough["antes"] else math.nan,
                "score_despues": after["score"].mean() if enough["despues"] else math.nan,
                "diferencia": diff,
                "ic_inf": low,
                "ic_sup": high,
                "prop_neg_antes": (before["label"] == "neg").mean() if enough["antes"] else math.nan,
                "prop_neg_despues": (after["label"] == "neg").mean() if enough["despues"] else math.nan,
                "dias_antes": days_before,
                "dias_despues": days_after,
                "truncada": days_before < days or days_after < days,
                "insuficiente": not all(enough.values()),
            })
    return pd.DataFrame(rows, columns=MILESTONE_COLUMNS)
