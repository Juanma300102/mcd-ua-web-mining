"""Labeling sample, annotator sheets and label merge (no model output involved)."""

from __future__ import annotations

import hashlib
import re
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


def _as_bool(series: pd.Series) -> pd.Series:
    """Coerce `es_en_vivo` to booleans: NaN is False and odd strings are rejected."""
    values = []
    for value in series:
        if value is None or (not isinstance(value, str) and pd.isna(value)):
            values.append(False)
        elif isinstance(value, str):
            text = value.strip().lower()
            if text not in ("true", "false"):
                raise ValueError(f"es_en_vivo has a non-boolean value: {value!r}")
            values.append(text == "true")
        elif value in (0, 1):
            values.append(bool(value))
        else:
            raise ValueError(f"es_en_vivo has a non-boolean value: {value!r}")
    return pd.Series(values, index=series.index, dtype=bool)


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
    Also fails on duplicated ids and on non-boolean `es_en_vivo` values (NaN
    counts as not live).
    """
    if per_medio % len(ANOTADORES):
        raise ValueError(f"per_medio must be even to split between annotators, got {per_medio}")
    duplicated = notes["id"].astype(str).duplicated()
    if duplicated.any():
        raise ValueError(f"duplicated note ids: {notes.loc[duplicated, 'id'].head(3).tolist()}")
    eligible = notes[~_as_bool(notes["es_en_vivo"]) & notes["titulo"].fillna("").str.strip().ne("")]
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


def export_sheets(sample: pd.DataFrame, out_dir: Path, overwrite: bool = False) -> list[Path]:
    """Write `anotador_{a,b}.csv` with `id, texto, etiqueta` (empty) in sample order.

    The sheets hold neither the outlet nor any model output. They contain
    scraped text, so `out_dir` must stay under the gitignored `data/`.

    Existing sheets may already be filled by the annotators, so this raises
    `FileExistsError` instead of overwriting them unless `overwrite=True`.
    """
    out_dir = Path(out_dir)
    targets = {a: out_dir / f"anotador_{a}.csv" for a in ANOTADORES}
    existing = [p.name for p in targets.values() if p.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            f"{existing} already exist in {out_dir}; they may hold filled labels. "
            "Pass overwrite=True only if you really want to replace them."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for anotador in ANOTADORES:
        sheet = sample.loc[sample["anotador"] == anotador, ["id", "texto"]].assign(etiqueta="")
        path = targets[anotador]
        sheet[SHEET_COLUMNS].to_csv(path, index=False, encoding="utf-8-sig")
        paths.append(path)
    return paths


SHEET_NAME = re.compile(r"anotador_([a-z])\.csv$")


def _read_sheet(path: Path) -> pd.DataFrame:
    """Read one filled sheet: string ids, no fully blank rows, annotator from the name."""
    path = Path(path)
    found = SHEET_NAME.match(path.name)
    if not found or found.group(1) not in ANOTADORES:
        raise ValueError(f"{path.name}: expected a sheet named anotador_a.csv or anotador_b.csv")
    sheet = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    missing = {"id", "etiqueta"} - set(sheet.columns)
    if missing:
        raise ValueError(f"{path.name}: missing columns {sorted(missing)}")
    sheet = sheet[sheet.apply(lambda row: row.str.strip().ne("").any(), axis=1)].copy()
    sheet["id"] = sheet["id"].str.strip()
    sheet["_hoja"] = found.group(1)
    return sheet[["id", "etiqueta", "_hoja"]]


def read_labels(paths: list[Path], sample: pd.DataFrame) -> pd.DataFrame:
    """Validate the filled sheets and return `id, anotador, etiqueta` (no text).

    Sheets must be named `anotador_a.csv` / `anotador_b.csv`. Labels are
    trimmed and lowercased. Rows that are entirely blank (spreadsheet leftovers)
    are ignored. Rejects labels outside `LABELS`, blank labels or ids, ids that
    are not in the sample, ids that belong to the other annotator (swapped
    files) and duplicated ids, and requires every sample id to be labeled.
    Ids are compared as strings on both sides.
    """
    labels = pd.concat([_read_sheet(p) for p in paths], ignore_index=True)
    labels["etiqueta"] = labels["etiqueta"].str.strip().str.lower()
    no_id = labels["id"] == ""
    if no_id.any():
        raise ValueError(f"{int(no_id.sum())} rows without id")
    blank = labels["etiqueta"] == ""
    if blank.any():
        raise ValueError(f"{int(blank.sum())} blank labels, e.g. ids {labels.loc[blank, 'id'].head(3).tolist()}")
    unknown = ~labels["etiqueta"].isin(LABELS)
    if unknown.any():
        bad = sorted(labels.loc[unknown, "etiqueta"].unique())
        raise ValueError(f"unknown labels {bad}; allowed: {list(LABELS)}")
    reference = sample[["id", "anotador"]].assign(id=sample["id"].astype(str))
    foreign = ~labels["id"].isin(reference["id"])
    if foreign.any():
        raise ValueError(f"ids not in the sample: {labels.loc[foreign, 'id'].head(3).tolist()}")
    dup = labels["id"].duplicated()
    if dup.any():
        raise ValueError(f"duplicated ids: {labels.loc[dup, 'id'].head(3).tolist()}")
    absent = ~reference["id"].isin(labels["id"])
    if absent.any():
        raise ValueError(f"{int(absent.sum())} sample ids have no label")
    merged = labels.merge(reference, on="id", how="left")
    swapped = merged["anotador"] != merged["_hoja"]
    if swapped.any():
        raise ValueError(
            f"{int(swapped.sum())} ids are in the other annotator's sheet (swapped files?), "
            f"e.g. {merged.loc[swapped, 'id'].head(3).tolist()}"
        )
    return merged[LABEL_COLUMNS].sort_values("id").reset_index(drop=True)
