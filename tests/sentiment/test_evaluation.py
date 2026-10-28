import math

import pandas as pd
import pytest

from news_politica.sentiment.evaluation import evaluate


def frames(true, pred, modelo="m", medio="infobae", fuente="bajada"):
    ids = [f"n{i}" for i in range(len(true))]
    labels = pd.DataFrame({"id": ids, "anotador": "a", "etiqueta": true})
    scores = pd.DataFrame({"id": ids, "modelo": modelo, "medio": medio, "fuente_texto": fuente, "label": pred})
    return labels, scores


def cell(confusion, true, pred, **where):
    frame = confusion[(confusion["etiqueta"] == true) & (confusion["prediccion"] == pred)]
    for column, value in where.items():
        frame = frame[frame[column] == value]
    (value,) = frame["n"]
    return value


def test_hand_computed_macro_f1_and_confusion():
    true = ["pos", "pos", "pos", "neu", "neu", "neg", "neg", "neg"]
    pred = ["pos", "pos", "neu", "neu", "neg", "neg", "neg", "pos"]
    metrics, confusion = evaluate(*frames(true, pred))
    (row,) = metrics.to_dict("records")
    # pos: tp 2, fp 1, fn 1 -> 2/3; neu: tp 1, fp 1, fn 1 -> 1/2; neg: tp 2, fp 1, fn 1 -> 2/3
    assert row["n"] == 8 and row["accuracy"] == pytest.approx(5 / 8)
    assert (row["f1_pos"], row["f1_neu"], row["f1_neg"]) == pytest.approx((2 / 3, 1 / 2, 2 / 3))
    assert row["macro_f1"] == pytest.approx((2 / 3 + 1 / 2 + 2 / 3) / 3)
    assert len(confusion) == 12  # 3 true classes x (3 predictions + sin_respuesta)
    assert cell(confusion, "pos", "pos") == 2 and cell(confusion, "pos", "neu") == 1
    assert cell(confusion, "neu", "neg") == 1 and cell(confusion, "neg", "pos") == 1
    assert cell(confusion, "neg", "sin_respuesta") == 0
    assert confusion["n"].sum() == 8


def test_perfect_agreement():
    metrics, _ = evaluate(*frames(["pos", "neu", "neg", "neg"], ["pos", "neu", "neg", "neg"]))
    assert metrics.loc[0, "accuracy"] == 1.0 and metrics.loc[0, "macro_f1"] == 1.0


def test_perfect_agreement_with_a_missing_class_is_still_one():
    metrics, _ = evaluate(*frames(["pos", "neg"], ["pos", "neg"]))
    assert metrics.loc[0, "macro_f1"] == 1.0 and math.isnan(metrics.loc[0, "f1_neu"])


def test_discarded_notes_are_excluded():
    true = ["pos"] * 290 + ["descartar"] * 10
    pred = ["pos"] * 280 + ["neg"] * 10 + ["neg"] * 10
    metrics, confusion = evaluate(*frames(true, pred))
    assert metrics.loc[0, "n"] == 290
    assert metrics.loc[0, "accuracy"] == pytest.approx(280 / 290)
    assert confusion["n"].sum() == 290


def test_unparsed_outputs_count_as_misses():
    metrics, confusion = evaluate(*frames(["pos", "neg"], ["pos", None]))
    assert metrics.loc[0, "n"] == 2 and metrics.loc[0, "accuracy"] == 0.5
    assert metrics.loc[0, "f1_neg"] == 0.0
    assert cell(confusion, "neg", "sin_respuesta") == 1


def test_per_model_rows_are_separate():
    labels, a = frames(["pos", "neg"], ["pos", "neg"], modelo="a")
    _, b = frames(["pos", "neg"], ["neg", "pos"], modelo="b")
    metrics, confusion = evaluate(labels, pd.concat([a, b]))
    assert metrics.set_index("modelo")["accuracy"].to_dict() == {"a": 1.0, "b": 0.0}
    assert set(confusion["modelo"]) == {"a", "b"}


def test_per_outlet_and_per_fuente_texto_rows():
    labels, one = frames(["pos", "neg"], ["pos", "neg"], medio="infobae", fuente="bajada")
    _, two = frames(["pos", "neg"], ["neg", "neg"], medio="lanacion", fuente="titulo")
    two["id"] = ["m0", "m1"]
    labels = pd.concat([labels, labels.assign(id=["m0", "m1"])])
    scores = pd.concat([one, two])
    by_medio, confusion = evaluate(labels, scores, by=("modelo", "medio"))
    assert by_medio.set_index("medio")["macro_f1"].round(3).to_dict() == {"infobae": 1.0, "lanacion": 0.333}
    assert list(by_medio.columns[:2]) == ["modelo", "medio"] and set(confusion["medio"]) == {"infobae", "lanacion"}
    by_fuente, _ = evaluate(labels, scores, by=("modelo", "fuente_texto"))
    assert by_fuente.set_index("fuente_texto")["n"].to_dict() == {"bajada": 2, "titulo": 2}


def test_only_ids_present_in_both_are_compared():
    labels, scores = frames(["pos", "neg", "neu"], ["pos", "neg", "neu"])
    metrics, _ = evaluate(labels, scores.iloc[:2])
    assert metrics.loc[0, "n"] == 2


def test_bad_inputs_are_rejected():
    labels, scores = frames(["pos"], ["pos"])
    with pytest.raises(ValueError, match="lacks the columns"):
        evaluate(labels, scores, by=("modelo", "nope"))
    with pytest.raises(ValueError, match="unknown labels"):
        evaluate(labels.assign(etiqueta="meh"), scores)


def test_empty_input_gives_empty_frames():
    labels, scores = frames([], [])
    metrics, confusion = evaluate(labels, scores)
    assert metrics.empty and confusion.empty


def test_duplicate_label_ids_are_rejected():
    labels, scores = frames(["pos", "neg"], ["pos", "neg"])
    with pytest.raises(ValueError, match="duplicated ids in labels"):
        evaluate(pd.concat([labels, labels.iloc[:1]]), scores)


def test_duplicate_scores_per_model_are_rejected_but_other_models_may_repeat_ids():
    labels, scores = frames(["pos", "neg"], ["pos", "neg"])
    with pytest.raises(ValueError, match="duplicated .*in scores"):
        evaluate(labels, pd.concat([scores, scores.iloc[:1]]))
    evaluate(labels, pd.concat([scores, scores.assign(modelo="other")]))  # same ids, another model: fine


def test_missing_group_keys_are_rejected():
    labels, scores = frames(["pos", "neg"], ["pos", "neg"])
    scores.loc[1, "medio"] = None
    with pytest.raises(ValueError, match="missing values in the grouping columns"):
        evaluate(labels, scores, by=("modelo", "medio"))


def test_predictions_outside_the_classes_are_rejected_so_totals_match_n():
    with pytest.raises(ValueError, match="unknown predictions"):
        evaluate(*frames(["pos", "neg"], ["pos", "mixed"]))


def test_confusion_totals_equal_n_with_unparsed_notes():
    metrics, confusion = evaluate(*frames(["pos", "neg", "neu", "neu"], ["pos", None, float("nan"), "neu"]))
    assert metrics.loc[0, "n"] == 4 and confusion["n"].sum() == 4
    assert cell(confusion, "neg", "sin_respuesta") == 1 and cell(confusion, "neu", "sin_respuesta") == 1


def test_group_columns_come_first_in_the_confusion_matrix():
    labels, scores = frames(["pos", "neg"], ["pos", "neg"])
    _, confusion = evaluate(labels, scores, by=("modelo", "medio", "fuente_texto"))
    assert list(confusion.columns) == ["modelo", "medio", "fuente_texto", "etiqueta", "prediccion", "n"]
