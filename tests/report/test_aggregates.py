import json
import math
from datetime import datetime, timezone

import pandas as pd
import pytest

from news_politica.report.aggregates import (
    build_payload,
    milestones,
    monthly_tone,
    outlet_summary,
    provincial_split,
)
from news_politica.sources.text import ART


def art(*args):
    return datetime(*args, tzinfo=ART)


def label_of(score):
    return "pos" if score > 0.2 else "neg" if score < -0.2 else "neu"


def make(rows, modelos=("m",)):
    """Notes and scores from dicts with `medio`, `moment`, `score` and optional `live`, `fuente`, `titulo`."""
    notes, scores = [], []
    for i, row in enumerate(rows):
        note_id = f"n{i:03d}"
        notes.append({
            "id": note_id, "medio": row["medio"], "fecha_publicacion": row["moment"].astimezone(timezone.utc),
            "es_en_vivo": row.get("live", False), "fuente_externa": row.get("fuente"),
            "titulo": row.get("titulo", f"Titulo {i}"),
        })
        for modelo in modelos:
            score = row["score"]
            pos, neg = max(score, 0.0), max(-score, 0.0)
            scores.append({
                "id": note_id, "modelo": modelo, "fuente_texto": "bajada", "label": label_of(score), "score": score,
                "prob_pos": pos, "prob_neg": neg, "prob_neu": 1 - pos - neg,
            })
    return pd.DataFrame(scores), pd.DataFrame(notes)


def test_monthly_point_excludes_live_notes():
    rows = [{"medio": "infobae", "moment": art(2025, 3, d), "score": s} for d, s in ((2, 0.2), (9, 0.4), (16, 0.0), (23, -0.2))]
    rows.append({"medio": "infobae", "moment": art(2025, 3, 30), "score": 0.9, "live": True})
    scores, notes = make(rows)
    month = monthly_tone(scores, notes, "m").iloc[0]
    assert (month["mes"], month["n"]) == ("2025-03", 4)
    assert month["score"] == pytest.approx(0.1)
    assert month["ic_inf"] < 0.1 < month["ic_sup"]


def test_month_is_art_calendar_month():
    # 2025-03-31 23:30 ART is already April in UTC.
    scores, notes = make([{"medio": "infobae", "moment": art(2025, 3, 31, 23, 30), "score": 0.5}])
    assert monthly_tone(scores, notes, "m")["mes"].tolist() == ["2025-03"]


def test_month_with_one_note_has_no_interval():
    scores, notes = make([{"medio": "lanacion", "moment": art(2024, 5, 3), "score": -0.4}])
    month = monthly_tone(scores, notes, "m").iloc[0]
    assert month["n"] == 1 and month["score"] == pytest.approx(-0.4)
    assert math.isnan(month["ic_inf"]) and math.isnan(month["ic_sup"])


def test_outlet_shares_sum_to_one():
    rows = [{"medio": "infobae", "moment": art(2024, 1, d), "score": s} for d, s in ((1, -0.5), (2, -0.6), (3, 0.0), (4, 0.5))]
    scores, notes = make(rows)
    row = outlet_summary(scores, notes, "m").iloc[0]
    assert (row["prop_neg"], row["prop_neu"], row["prop_pos"]) == pytest.approx((0.5, 0.25, 0.25))
    assert row["n"] == 4


def test_unknown_model_raises():
    scores, notes = make([{"medio": "infobae", "moment": art(2024, 1, 1), "score": 0.1}])
    with pytest.raises(ValueError, match="no scores for modelo"):
        outlet_summary(scores, notes, "otro")


def test_provincial_split_by_fuente_externa():
    rows = [{"medio": "misionesonline", "moment": art(2024, 2, d), "score": 0.1, "fuente": f} for d, f in
            ((1, None), (2, ""), (3, "  "), (4, "TN"), (5, "TN"))]
    rows.append({"medio": "infobae", "moment": art(2024, 2, 6), "score": -0.3, "fuente": None})
    scores, notes = make(rows, modelos=("a", "b"))
    split = provincial_split(scores, notes).set_index(["modelo", "grupo"])["n"]
    assert split.to_dict() == {("a", "propias"): 3, ("a", "reproducidas"): 2, ("b", "propias"): 3, ("b", "reproducidas"): 2}


def window_rows(medio, day, before, after):
    """Notes spread inside the 14 days before and after `day` (a datetime at 00:00 ART)."""
    rows = [{"medio": medio, "moment": day - pd.Timedelta(hours=10 * (i + 1)), "score": s} for i, s in enumerate(before)]
    rows += [{"medio": medio, "moment": day + pd.Timedelta(hours=10 * i + 1), "score": s} for i, s in enumerate(after)]
    return rows


def test_milestone_clear_only_when_interval_excludes_zero():
    day = art(2025, 10, 26)
    rows = window_rows("infobae", day, [-0.5, -0.6, -0.4] * 4, [0.4, 0.5, 0.6] * 4)  # clear rise
    rows += window_rows("lanacion", day, [-0.5, 0.5, 0.0] * 4, [0.5, -0.5, 0.1] * 4)  # noise
    rows += window_rows("misionesonline", day, [0.1] * 3, [0.2] * 12)  # too few before
    scores, notes = make(rows)
    hitos = pd.DataFrame([{"hito": "Elecciones", "fecha": "2025-10-26", "alcance": "nacional"}])
    table = milestones(scores, notes, hitos, "m").set_index("medio")
    assert bool(table.loc["infobae", "claro"]) is True
    assert table.loc["lanacion", "ic_inf"] < 0 < table.loc["lanacion", "ic_sup"]
    assert bool(table.loc["lanacion", "claro"]) is False
    assert bool(table.loc["misionesonline", "insuficiente"]) is True
    assert math.isnan(table.loc["misionesonline", "score_antes"])
    assert bool(table.loc["misionesonline", "claro"]) is False
    assert table.loc["infobae", "fecha"] == "2025-10-26"


def test_payload_is_plain_json():
    rows = [{"medio": m, "moment": art(2024, 6, d), "score": s} for m in ("infobae", "lanacion", "misionesonline")
            for d, s in ((1, -0.3), (2, 0.1), (20, 0.4))]
    rows.append({"medio": "infobae", "moment": art(2024, 7, 1), "score": 0.2})  # single-note month: null interval
    scores, notes = make(rows, modelos=("m", "otro"))
    labels = pd.DataFrame({"id": notes["id"], "etiqueta": [label_of(s) for s in (r["score"] for r in rows)]})
    hitos = pd.DataFrame([{"hito": "H", "fecha": "2024-06-15", "alcance": "nacional"}])
    payload = build_payload(scores, notes, labels, hitos, "m")
    text = json.dumps(payload, allow_nan=False)  # raises on NaN
    assert "NaN" not in text
    assert payload["totales"]["notas"] == 10
    assert {r["modelo"] for r in payload["evaluacion"]} == {"m", "otro"}
