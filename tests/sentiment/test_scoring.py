import math

import pandas as pd

from news_politica.sentiment.scoring import SCORE_COLUMNS, score_notes

NAN = (math.nan, math.nan, math.nan)


class KeywordClassifier:
    """Maps keywords in the text to fixed (pos, neu, neg) probabilities."""

    name = "fake"
    device = "cpu"

    def __init__(self):
        self.batches = []

    def predict(self, texts):
        self.batches.append(list(texts))
        out = []
        for text in texts:
            if "bien" in text:
                out.append((0.7, 0.2, 0.1))
            elif "mal" in text:
                out.append((0.1, 0.2, 0.7))
            elif "raro" in text:
                out.append(NAN)
            else:
                out.append((0.2, 0.6, 0.2))
        return out


class ListLog:
    def __init__(self):
        self.lines = []

    def info(self, message):
        self.lines.append(message)


def make_notes(titles, bajada="Bajada"):
    return pd.DataFrame(
        {
            "id": [f"n{i}" for i in range(len(titles))],
            "titulo": titles,
            "bajada": bajada,
            "cuerpo": "Cuerpo.",
        }
    )


def test_one_row_per_note_with_score_and_label():
    notes = make_notes(["todo bien", "todo mal", "nada"])
    out = score_notes(notes, KeywordClassifier(), batch_size=2)
    assert list(out.columns) == SCORE_COLUMNS
    assert out["id"].tolist() == ["n0", "n1", "n2"]
    assert (out["modelo"] == "fake").all()
    assert out["label"].tolist() == ["pos", "neg", "neu"]
    assert out["score"].tolist() == [0.7 - 0.1, 0.1 - 0.7, 0.0]
    assert (out[["prob_pos", "prob_neu", "prob_neg"]].sum(axis=1).round(9) == 1).all()


def test_model_input_is_the_analysis_text():
    classifier = KeywordClassifier()
    out = score_notes(make_notes(["Titulo bien"]), classifier)
    assert classifier.batches == [["Titulo bien. Bajada"]]
    assert out["fuente_texto"].tolist() == ["bajada"]


def test_unparsed_rows_keep_label_none_and_are_counted():
    log = ListLog()
    out = score_notes(make_notes(["bien", "raro", "mal"]), KeywordClassifier(), log=log)
    assert out["label"].tolist() == ["pos", None, "neg"]
    assert out["score"].isna().tolist() == [False, True, False]
    assert log.lines[-1] == "fake: 3 notes scored (1 neg, 0 neu, 1 pos, 1 unparsed)"


def test_progress_is_logged_every_ten_batches():
    log = ListLog()
    out = score_notes(make_notes(["bien"] * 25), KeywordClassifier(), batch_size=1, log=log)
    assert len(out) == 25
    assert log.lines[:2] == ["fake: 10/25 notes scored", "fake: 20/25 notes scored"]
    assert len(log.lines) == 3
    assert log.lines[2].startswith("fake: 25 notes scored")


def test_works_without_a_log_and_with_no_notes():
    assert len(score_notes(make_notes(["bien"]), KeywordClassifier())) == 1
    empty = score_notes(make_notes([]), KeywordClassifier(), log=ListLog())
    assert list(empty.columns) == SCORE_COLUMNS
    assert empty.empty
