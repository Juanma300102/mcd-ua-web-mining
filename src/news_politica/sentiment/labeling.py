"""Labeling sample, annotator sheets and label merge (no model output involved)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from news_politica.sentiment.text import analysis_text

SAMPLE_SALT = "etiquetado-2026-10"
MEDIOS = ("misionesonline", "infobae", "lanacion")
ANOTADORES = ("a", "b")
LABELS = ("pos", "neu", "neg", "descartar")
SAMPLE_COLUMNS = ["id", "medio", "texto", "fuente_texto", "anotador"]
SHEET_COLUMNS = ["id", "texto", "etiqueta"]
LABEL_COLUMNS = ["id", "anotador", "etiqueta"]


def _hash_key(salt: str, note_id: str) -> str:
    return hashlib.sha1((salt + str(note_id)).encode()).hexdigest()


def labeling_sample(
    notes: pd.DataFrame,
    per_medio: int = 100,
    salt: str = SAMPLE_SALT,
    medios: tuple[str, ...] = MEDIOS,
) -> pd.DataFrame:
    """Draw `per_medio` notes per outlet and split them between annotators a and b.

    Eligible notes are not live and have a non-empty title. Within each outlet
    they are ordered by `sha1(salt + id)`, the first `per_medio` are kept and
    annotators alternate down that order, so each gets half of every outlet with
    no overlap. The draw does not depend on row order. Rows come back in global
    hash order, so sheets do not group notes by outlet.

    Fails with a clear message when an outlet is missing or has fewer eligible
    notes than `per_medio`: the sample must come from the full, frozen dataset.
    """
    if per_medio % len(ANOTADORES):
        raise ValueError(f"per_medio must be even to split between annotators, got {per_medio}")
    eligible = notes[~notes["es_en_vivo"].astype(bool) & notes["titulo"].fillna("").str.strip().ne("")]
    parts = []
    for medio in medios:
        pool = eligible[eligible["medio"] == medio]
        if len(pool) < per_medio:
            raise ValueError(
                f"{medio}: {len(pool)} eligible notes, {per_medio} needed. "
                "Draw the sample only from the shared, frozen full dataset with all outlets."
            )
        pool = pool.assign(_key=[_hash_key(salt, i) for i in pool["id"]]).sort_values("_key")
        pool = pool.head(per_medio).copy()
        pool["anotador"] = [ANOTADORES[n % len(ANOTADORES)] for n in range(per_medio)]
        parts.append(pool)
    sample = pd.concat(parts)
    texts = [
        analysis_text(t, b, c)
        for t, b, c in zip(sample["titulo"], sample["bajada"], sample["cuerpo"], strict=True)
    ]
    sample["texto"] = [t for t, _ in texts]
    sample["fuente_texto"] = [s for _, s in texts]
    sample = sample.sort_values("_key")
    return sample[SAMPLE_COLUMNS].reset_index(drop=True)


def export_sheets(sample: pd.DataFrame, out_dir: Path) -> list[Path]:
    """Write `anotador_{a,b}.csv` with `id, texto, etiqueta` (empty) in sample order.

    The sheets hold neither the outlet nor any model output. They contain
    scraped text, so `out_dir` must stay under the gitignored `data/`.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for anotador in ANOTADORES:
        sheet = sample.loc[sample["anotador"] == anotador, ["id", "texto"]].assign(etiqueta="")
        path = out_dir / f"anotador_{anotador}.csv"
        sheet[SHEET_COLUMNS].to_csv(path, index=False, encoding="utf-8-sig")
        paths.append(path)
    return paths


def read_labels(paths: list[Path], sample: pd.DataFrame) -> pd.DataFrame:
    """Validate the filled sheets and return `id, anotador, etiqueta` (no text).

    Rejects labels outside `LABELS`, blank labels, ids that are not in the
    sample and duplicated ids, and requires every sample id to be labeled.
    """
    frames = [
        pd.read_csv(p, dtype=str, keep_default_na=False, encoding="utf-8-sig") for p in paths
    ]
    labels = pd.concat(frames, ignore_index=True)
    missing_cols = {"id", "etiqueta"} - set(labels.columns)
    if missing_cols:
        raise ValueError(f"missing columns in the sheets: {sorted(missing_cols)}")
    labels["etiqueta"] = labels["etiqueta"].str.strip().str.lower()
    blank = labels["etiqueta"] == ""
    if blank.any():
        raise ValueError(f"{int(blank.sum())} blank labels, e.g. ids {labels.loc[blank, 'id'].head(3).tolist()}")
    unknown = ~labels["etiqueta"].isin(LABELS)
    if unknown.any():
        bad = sorted(labels.loc[unknown, "etiqueta"].unique())
        raise ValueError(f"unknown labels {bad}; allowed: {list(LABELS)}")
    foreign = ~labels["id"].isin(sample["id"])
    if foreign.any():
        raise ValueError(f"ids not in the sample: {labels.loc[foreign, 'id'].head(3).tolist()}")
    dup = labels["id"].duplicated()
    if dup.any():
        raise ValueError(f"duplicated ids: {labels.loc[dup, 'id'].head(3).tolist()}")
    absent = ~sample["id"].isin(labels["id"])
    if absent.any():
        raise ValueError(f"{int(absent.sum())} sample ids have no label")
    merged = labels.merge(sample[["id", "anotador"]], on="id", how="left")
    return merged[LABEL_COLUMNS].sort_values("id").reset_index(drop=True)
