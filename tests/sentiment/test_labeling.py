import pandas as pd
import pytest

from news_politica.sentiment.labeling import (
    LABEL_COLUMNS,
    MEDIOS,
    export_sheets,
    labeling_sample,
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
