import pandas as pd
import pytest

from news_politica.sentiment.labeling import (
    LABEL_COLUMNS,
    MEDIOS,
    export_sheets,
    labeling_sample,
    load_labels,
    read_labels,
)

PER_MEDIO = 4


def make_notes(n=12):
    rows = []
    for medio in MEDIOS:
        for i in range(n):
            rows.append(
                {
                    "id": f"{medio}-{i:02d}",
                    "medio": medio,
                    "titulo": f"Titulo {medio} {i}",
                    "bajada": f"Bajada {i}" if i % 2 else "",
                    "cuerpo": f"Primer parrafo {i}.\n\nSegundo.",
                    "es_en_vivo": False,
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture
def notes():
    return make_notes()


@pytest.fixture
def sample(notes):
    return labeling_sample(notes, per_medio=PER_MEDIO)


def test_live_notes_and_empty_titles_are_excluded(notes):
    notes.loc[notes["id"].str.endswith("-00"), "es_en_vivo"] = True
    notes.loc[notes["id"].str.endswith("-01"), "titulo"] = "  "
    s = labeling_sample(notes, per_medio=PER_MEDIO)
    assert not s["id"].str.endswith(("-00", "-01")).any()


def test_size_per_outlet(sample):
    assert sample.groupby("medio").size().to_dict() == {m: PER_MEDIO for m in MEDIOS}
    assert list(sample.columns) == ["id", "medio", "texto", "fuente_texto", "anotador"]


def test_same_ids_after_shuffling_rows(notes, sample):
    shuffled = notes.sample(frac=1, random_state=3).reset_index(drop=True)
    again = labeling_sample(shuffled, per_medio=PER_MEDIO)
    pd.testing.assert_frame_equal(again, sample)


def test_split_is_disjoint_and_balanced_per_outlet(sample):
    a = sample[sample["anotador"] == "a"]
    b = sample[sample["anotador"] == "b"]
    assert set(a["id"]).isdisjoint(b["id"])
    for medio in MEDIOS:
        assert (a["medio"] == medio).sum() == (b["medio"] == medio).sum() == PER_MEDIO // 2


def test_too_few_notes_fails_with_clear_message(notes):
    with pytest.raises(ValueError, match="frozen full dataset"):
        labeling_sample(notes[notes["medio"] != "misionesonline"], per_medio=PER_MEDIO)
    with pytest.raises(ValueError, match="infobae: 3 eligible"):
        labeling_sample(notes.drop(notes[notes["medio"] == "infobae"].index[3:]), per_medio=PER_MEDIO)


def test_export_sheets_columns_and_no_outlet(sample, tmp_path):
    paths = export_sheets(sample, tmp_path / "etiquetado")
    assert [p.name for p in paths] == ["anotador_a.csv", "anotador_b.csv"]
    for p, anotador in zip(paths, "ab"):
        sheet = pd.read_csv(p, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        assert list(sheet.columns) == ["id", "texto", "etiqueta"]
        assert (sheet["etiqueta"] == "").all()
        assert sheet["id"].tolist() == sample.loc[sample["anotador"] == anotador, "id"].tolist()
        assert len(sheet) == PER_MEDIO * len(MEDIOS) // 2


def fill(paths, label="neu"):
    for p in paths:
        sheet = pd.read_csv(p, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        sheet["etiqueta"] = label
        sheet.to_csv(p, index=False, encoding="utf-8-sig")


def test_read_labels_returns_only_id_annotator_label(sample, tmp_path):
    paths = export_sheets(sample, tmp_path)
    fill(paths)
    labels = read_labels(paths, sample)
    assert list(labels.columns) == LABEL_COLUMNS
    assert len(labels) == len(sample)
    assert "texto" not in labels.columns


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda s: s.__setitem__("etiqueta", s["etiqueta"].where(s.index != 0, "bueno")), "unknown labels"),
        (lambda s: s.__setitem__("etiqueta", s["etiqueta"].where(s.index != 0, "")), "blank"),
        (lambda s: s.__setitem__("id", s["id"].where(s.index != 0, "otro-id")), "not in the sample"),
    ],
)
def test_read_labels_rejects_bad_sheets(sample, tmp_path, mutate, match):
    paths = export_sheets(sample, tmp_path)
    fill(paths)
    sheet = pd.read_csv(paths[0], dtype=str, keep_default_na=False, encoding="utf-8-sig")
    mutate(sheet)
    sheet.to_csv(paths[0], index=False, encoding="utf-8-sig")
    with pytest.raises(ValueError, match=match):
        read_labels(paths, sample)


def test_read_labels_rejects_duplicates(sample, tmp_path):
    paths = export_sheets(sample, tmp_path)
    fill(paths)
    sheet = pd.read_csv(paths[0], dtype=str, keep_default_na=False, encoding="utf-8-sig")
    sheet = pd.concat([sheet, sheet.head(1)])
    sheet.to_csv(paths[0], index=False, encoding="utf-8-sig")
    with pytest.raises(ValueError, match="duplicated"):
        read_labels(paths, sample)


def test_read_labels_requires_every_sample_id(sample, tmp_path):
    paths = export_sheets(sample, tmp_path)
    fill(paths)
    with pytest.raises(ValueError, match="no label"):
        read_labels(paths[:1], sample)


def test_export_sheets_does_not_overwrite_filled_sheets(sample, tmp_path):
    paths = export_sheets(sample, tmp_path)
    fill(paths)
    with pytest.raises(FileExistsError, match="already exist"):
        export_sheets(sample, tmp_path)
    sheet = pd.read_csv(paths[0], dtype=str, keep_default_na=False, encoding="utf-8-sig")
    assert (sheet["etiqueta"] == "neu").all()
    export_sheets(sample, tmp_path, overwrite=True)
    sheet = pd.read_csv(paths[0], dtype=str, keep_default_na=False, encoding="utf-8-sig")
    assert (sheet["etiqueta"] == "").all()


def test_export_sheets_refuses_when_only_one_sheet_exists(sample, tmp_path):
    (tmp_path / "anotador_b.csv").write_text("id,texto,etiqueta\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        export_sheets(sample, tmp_path)
    assert not (tmp_path / "anotador_a.csv").exists()


def test_duplicate_note_ids_are_rejected(notes):
    dup = pd.concat([notes, notes.head(1)], ignore_index=True)
    with pytest.raises(ValueError, match="duplicated note ids"):
        labeling_sample(dup, per_medio=PER_MEDIO)


def test_es_en_vivo_nan_counts_as_not_live(notes):
    notes["es_en_vivo"] = notes["es_en_vivo"].astype(object)
    notes.loc[notes["id"].str.endswith("-00"), "es_en_vivo"] = float("nan")
    notes.loc[notes["id"].str.endswith("-01"), "es_en_vivo"] = True
    s = labeling_sample(notes, per_medio=PER_MEDIO)
    assert not s["id"].str.endswith("-01").any()
    assert len(s) == PER_MEDIO * len(MEDIOS)


def test_es_en_vivo_boolean_strings_are_parsed_and_others_rejected(notes):
    notes["es_en_vivo"] = notes["es_en_vivo"].astype(object)
    notes.loc[notes["id"].str.endswith("-01"), "es_en_vivo"] = "True"
    notes.loc[notes["id"].str.endswith("-02"), "es_en_vivo"] = "false"
    s = labeling_sample(notes, per_medio=PER_MEDIO)
    assert not s["id"].str.endswith("-01").any()
    notes.loc[notes["id"].str.endswith("-03"), "es_en_vivo"] = "no"
    with pytest.raises(ValueError, match="non-boolean"):
        labeling_sample(notes, per_medio=PER_MEDIO)


def test_read_labels_normalizes_whitespace_and_case(sample, tmp_path):
    paths = export_sheets(sample, tmp_path)
    fill(paths, " POS ")
    labels = read_labels(paths, sample)
    assert set(labels["etiqueta"]) == {"pos"}


def test_read_labels_missing_column_names_the_sheet(sample, tmp_path):
    paths = export_sheets(sample, tmp_path)
    fill(paths)
    sheet = pd.read_csv(paths[1], dtype=str, keep_default_na=False, encoding="utf-8-sig")
    sheet.drop(columns="etiqueta").to_csv(paths[1], index=False, encoding="utf-8-sig")
    with pytest.raises(ValueError, match=r"anotador_b.csv: missing columns \['etiqueta'\]"):
        read_labels(paths, sample)


def test_read_labels_ignores_trailing_blank_rows(sample, tmp_path):
    paths = export_sheets(sample, tmp_path)
    fill(paths)
    with open(paths[0], "a", encoding="utf-8-sig") as f:
        f.write(",,\n , ,\n")
    labels = read_labels(paths, sample)
    assert len(labels) == len(sample)


def test_read_labels_rejects_row_with_label_but_no_id(sample, tmp_path):
    paths = export_sheets(sample, tmp_path)
    fill(paths)
    with open(paths[0], "a", encoding="utf-8-sig") as f:
        f.write(",,neu\n")
    with pytest.raises(ValueError, match="without id"):
        read_labels(paths, sample)


def test_read_labels_detects_swapped_sheets(sample, tmp_path):
    paths = export_sheets(sample, tmp_path)
    fill(paths)
    a, b = (p.read_bytes() for p in paths)
    paths[0].write_bytes(b)
    paths[1].write_bytes(a)
    with pytest.raises(ValueError, match="other annotator"):
        read_labels(paths, sample)


def test_read_labels_compares_ids_as_strings(tmp_path):
    notes = make_notes()
    notes["id"] = [str(i) for i in range(len(notes))]
    s = labeling_sample(notes, per_medio=PER_MEDIO)
    s["id"] = s["id"].astype(int)
    paths = export_sheets(s, tmp_path)
    fill(paths)
    labels = read_labels(paths, s)
    assert len(labels) == len(s)


def committed(sample, tmp_path, **changes):
    """A committed-style labels file (`id, anotador, etiqueta`), optionally altered."""
    frame = sample[["id", "anotador"]].assign(etiqueta="neu")
    for column, value in changes.items():
        frame[column] = value
    path = tmp_path / "etiquetas.csv"
    frame.to_csv(path, index=False)
    return path


def test_load_labels_reads_the_committed_file(sample, tmp_path):
    labels = load_labels(committed(sample, tmp_path), sample)
    assert list(labels.columns) == LABEL_COLUMNS and len(labels) == len(sample)
    assert set(labels["etiqueta"]) == {"neu"}


def test_load_labels_rejects_the_same_problems_as_read_labels(sample, tmp_path):
    with pytest.raises(ValueError, match="unknown labels"):
        load_labels(committed(sample, tmp_path, etiqueta="meh"), sample)
    with pytest.raises(ValueError, match="blank labels"):
        load_labels(committed(sample, tmp_path, etiqueta=""), sample)
    swapped = sample["anotador"].map({"a": "b", "b": "a"})
    with pytest.raises(ValueError, match="other annotator"):
        load_labels(committed(sample, tmp_path, anotador=swapped), sample)
    path = committed(sample, tmp_path)
    pd.read_csv(path, dtype=str).head(len(sample) - 1).to_csv(path, index=False)
    with pytest.raises(ValueError, match="no label"):
        load_labels(path, sample)


def test_load_labels_requires_exactly_the_committed_columns(sample, tmp_path):
    path = committed(sample, tmp_path)
    pd.read_csv(path, dtype=str).assign(texto="leaked").to_csv(path, index=False)
    with pytest.raises(ValueError, match="columns must be"):
        load_labels(path, sample)
