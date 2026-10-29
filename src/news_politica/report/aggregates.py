"""Every number of the narrative report, computed from the stored sentiment and notes frames.

Pure pandas and scipy; no Dagster, no models, no network. The eligibility rule (no live notes,
no unscored notes, no null dates), the t interval and the milestone comparison come from
`news_politica.sentiment.tone`, so the report counts the same notes as `evolucion_tono`.
Months are calendar months in Argentina time, keyed `YYYY-MM`.

`build_payload` returns plain JSON types only: NaN becomes None and floats are rounded, so
the data block in `docs/informe.html` is stable across rebuilds.
"""

from __future__ import annotations

import json
import math
import re

import pandas as pd

from news_politica.sentiment.evaluation import evaluate
from news_politica.sentiment.tone import _eligible, _half_width, compare_milestones
from news_politica.sources.text import ART

LABELS = ("neg", "neu", "pos")
DECIMALS = 3
DATA_BLOCK = re.compile(r'(<script type="application/json" id="datos">)(.*?)(</script>)', re.DOTALL)


def _clean(value):
    """A JSON-safe scalar: NaN and NaT become None, numpy numbers become Python numbers."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, bool):
        return value
    if hasattr(value, "item"):  # numpy scalar
        value = value.item()
    if isinstance(value, float):
        return None if math.isnan(value) else round(value, DECIMALS)
    return value


def _records(frame: pd.DataFrame) -> list[dict]:
    return [{k: _clean(v) for k, v in row.items()} for row in frame.to_dict("records")]


def _model(scores: pd.DataFrame, modelo: str) -> pd.DataFrame:
    selected = scores[scores["modelo"] == modelo]
    if selected.empty:
        raise ValueError(f"no scores for modelo {modelo!r}; present: {sorted(scores['modelo'].unique())}")
    return selected


def outlet_summary(scores: pd.DataFrame, notes: pd.DataFrame, modelo: str) -> pd.DataFrame:
    """Per outlet: `n`, mean `score` and the share of each label (`prop_neg`, `prop_neu`, `prop_pos`)."""
    data = _eligible(_model(scores, modelo), notes)
    for label in LABELS:
        data[f"prop_{label}"] = (data["label"] == label).astype(float)
    return data.groupby("medio", sort=True).agg(
        n=("score", "size"),
        score=("score", "mean"),
        **{f"prop_{label}": (f"prop_{label}", "mean") for label in LABELS},
    ).reset_index()


def outlet_means_by_model(scores: pd.DataFrame, notes: pd.DataFrame) -> pd.DataFrame:
    """Mean score per `(modelo, medio)`, to show that the ordering of the outlets holds for every model."""
    data = _eligible(scores, notes)
    return data.groupby(["modelo", "medio"], sort=True).agg(n=("score", "size"), score=("score", "mean")).reset_index()


def monthly_tone(scores: pd.DataFrame, notes: pd.DataFrame, modelo: str) -> pd.DataFrame:
    """Per outlet and ART month: `n`, mean `score` and its 95 % t interval (None below two notes)."""
    data = _eligible(_model(scores, modelo), notes)
    data["mes"] = data["momento"].dt.strftime("%Y-%m")
    monthly = data.groupby(["medio", "mes"], sort=True).agg(
        n=("score", "size"), score=("score", "mean"), sd=("score", "std"),
    ).reset_index()
    half = _half_width(monthly["sd"], monthly["n"])
    monthly["ic_inf"] = monthly["score"] - half
    monthly["ic_sup"] = monthly["score"] + half
    return monthly[["medio", "mes", "n", "score", "ic_inf", "ic_sup"]]


def provincial_split(scores: pd.DataFrame, notes: pd.DataFrame, medio: str = "misionesonline") -> pd.DataFrame:
    """Per model, the outlet's own notes (blank `fuente_externa`) vs the ones it reproduces: `n` and mean score."""
    data = _eligible(scores, notes)
    data = data[data["medio"] == medio]
    source = notes.set_index("id")["fuente_externa"].reindex(data["id"]).fillna("").astype(str).str.strip()
    data["grupo"] = (source.to_numpy() != "")
    data["grupo"] = data["grupo"].map({False: "propias", True: "reproducidas"})
    return data.groupby(["modelo", "grupo"], sort=True).agg(n=("score", "size"), score=("score", "mean")).reset_index()


def milestones(scores: pd.DataFrame, notes: pd.DataFrame, hitos: pd.DataFrame, modelo: str) -> pd.DataFrame:
    """`compare_milestones` for one model, plus `claro`: the difference interval excludes zero."""
    table = compare_milestones(_model(scores, modelo), notes, hitos)
    table["claro"] = (table["ic_inf"] > 0) | (table["ic_sup"] < 0)  # NaN compares False
    table["fecha"] = table["fecha"].astype(str)
    return table.drop(columns=["modelo"])


def volume(notes: pd.DataFrame) -> pd.DataFrame:
    """Notes per outlet and ART month, live notes included (the size of what was read)."""
    month = pd.to_datetime(notes["fecha_publicacion"], utc=True).dt.tz_convert(ART).dt.strftime("%Y-%m")
    return notes.assign(mes=month).groupby(["medio", "mes"], sort=True).size().rename("n").reset_index()


def model_evaluation(scores: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Accuracy and macro F1 of every model on the labeled sample (silver labels)."""
    metrics, _ = evaluate(labels[["id", "etiqueta"]], scores[["id", "modelo", "label"]])
    return metrics[["modelo", "n", "accuracy", "macro_f1"]]


def build_payload(
    scores: pd.DataFrame, notes: pd.DataFrame, labels: pd.DataFrame, hitos: pd.DataFrame, modelo: str
) -> dict:
    """Everything the report page reads, as plain JSON types."""
    moments = pd.to_datetime(notes["fecha_publicacion"], utc=True).dt.tz_convert(ART)
    live = notes["es_en_vivo"].fillna(False).astype(bool)
    return {
        "modelo": modelo,
        "periodo": {"desde": moments.min().strftime("%Y-%m-%d"), "hasta": moments.max().strftime("%Y-%m-%d")},
        "totales": {
            "notas": int(len(notes)),
            "en_vivo": int(live.sum()),
            "meses": int(moments.dt.strftime("%Y-%m").nunique()),
            "por_medio": {k: int(v) for k, v in notes["medio"].value_counts().sort_index().items()},
            "etiquetadas": int(len(labels)),
        },
        "volumen": _records(volume(notes)),
        "resumen": _records(outlet_summary(scores, notes, modelo)),
        "por_modelo": _records(outlet_means_by_model(scores, notes)),
        "mensual": _records(monthly_tone(scores, notes, modelo)),
        "hitos": _records(milestones(scores, notes, hitos, modelo)),
        "provincial": _records(provincial_split(scores, notes)),
        "evaluacion": _records(model_evaluation(scores, labels)),
    }


def replace_data_block(html: str, payload: dict) -> str:
    """`html` with the content of its single `datos` JSON block replaced by `payload`."""
    matches = DATA_BLOCK.findall(html)
    if len(matches) != 1:
        raise ValueError(f'expected exactly one <script type="application/json" id="datos"> block, found {len(matches)}')
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).replace("</", "<\\/")
    return DATA_BLOCK.sub(lambda m: f"{m.group(1)}\n{text}\n{m.group(3)}", html, count=1)
