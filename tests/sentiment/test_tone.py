import math
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from scipy import stats

from news_politica.sentiment.tone import N_MIN, WEEKLY_COLUMNS, compare_milestones, tone_exclusions, weekly_tone
from news_politica.sources.text import ART


def art(*args):
    return datetime(*args, tzinfo=ART)


def make(rows, modelo="m"):
    """Notes and scores from `(medio, moment, score)` or `(medio, moment, score, live)` rows."""
    notes, scores = [], []
    for i, row in enumerate(rows):
        medio, moment, score, *rest = row
        live = bool(rest and rest[0])
        label = None if math.isnan(score) else ("pos" if score > 0.2 else "neg" if score < -0.2 else "neu")
        notes.append({"id": f"n{i}", "medio": medio, "fecha_publicacion": moment.astimezone(timezone.utc),
                      "es_en_vivo": live})
        scores.append({"id": f"n{i}", "modelo": modelo, "fuente_texto": "bajada" if i % 2 == 0 else "titulo",
                       "label": label, "score": score})
    return pd.DataFrame(scores), pd.DataFrame(notes)


def week_row(frame, medio="infobae", **where):
    rows = frame[frame["medio"] == medio]
    for column, value in where.items():
        rows = rows[rows[column] == value]
    (row,) = rows.to_dict("records")
    return row


def test_sunday_night_art_belongs_to_that_sundays_week():
    # 23:30 ART on Sunday 2024-03-10 is 02:30 UTC on Monday the 11th.
    scores, notes = make([("infobae", art(2024, 3, 10, 23, 30), 0.1), ("infobae", art(2024, 3, 11, 0, 30), 0.1)])
    weekly = weekly_tone(scores, notes)
    assert list(weekly["n"]) == [1, 1]
    assert list(weekly["semana"]) == [pd.Timestamp(art(2024, 3, 4)), pd.Timestamp(art(2024, 3, 11))]
    assert list(weekly.columns) == WEEKLY_COLUMNS


def test_live_notes_and_nan_scores_are_excluded():
    rows = [("infobae", art(2024, 3, 5, 10), 0.5, True)] * 3 + [("infobae", art(2024, 3, 5, 11), 0.5)] * 2
    rows.append(("infobae", art(2024, 3, 5, 12), math.nan))
    assert weekly_tone(*make(rows)).loc[0, "n"] == 2


def test_weekly_mean_and_shares():
    rows = [("infobae", art(2024, 3, 5, h), s) for h, s in zip((9, 10, 11, 12), (0.2, 0.4, 0.0, -0.2), strict=True)]
    row = week_row(weekly_tone(*make(rows)))
    assert row["n"] == 4 and row["score_medio"] == pytest.approx(0.1)
    assert row["prop_pos"] + row["prop_neu"] + row["prop_neg"] == pytest.approx(1)
    assert (row["prop_pos"], row["prop_neu"], row["prop_neg"]) == pytest.approx((0.25, 0.75, 0.0))
    assert row["prop_bajada"] == pytest.approx(0.5)  # texts 0 and 2 of 0..3 came from the bajada


def test_t_interval_matches_a_known_value():
    rows = [("infobae", art(2024, 3, 5, h), s) for h, s in zip((9, 10, 11, 12), (0.2, 0.4, 0.0, -0.2), strict=True)]
    row = week_row(weekly_tone(*make(rows)))
    half = 3.182446305 * math.sqrt(0.2 / 3) / 2  # t(0.975, 3) * s / sqrt(n)
    assert row["ic_sup"] - row["score_medio"] == pytest.approx(half, rel=1e-6)
    assert row["score_medio"] - row["ic_inf"] == pytest.approx(half, rel=1e-6)
    assert stats.t.ppf(0.975, 3) == pytest.approx(3.182446305)


def test_single_note_week_has_n_and_mean_but_no_interval():
    row = week_row(weekly_tone(*make([("infobae", art(2024, 3, 5, 9), 0.3)])))
    assert row["n"] == 1 and row["score_medio"] == pytest.approx(0.3)
    assert math.isnan(row["ic_inf"]) and math.isnan(row["ic_sup"])


def test_outlets_and_models_are_separate_rows():
    scores, notes = make([("infobae", art(2024, 3, 5, 9), 0.1), ("lanacion", art(2024, 3, 5, 9), 0.2)])
    other = scores.assign(modelo="o", score=-0.5, label="neg")
    weekly = weekly_tone(pd.concat([scores, other]), notes)
    assert set(zip(weekly["modelo"], weekly["medio"], strict=True)) == {
        ("m", "infobae"), ("m", "lanacion"), ("o", "infobae"), ("o", "lanacion")}


def test_empty_input_gives_an_empty_frame_with_the_columns():
    scores, notes = make([("infobae", art(2024, 3, 5, 9), 0.1, True)])
    weekly = weekly_tone(scores, notes)
    assert weekly.empty and list(weekly.columns) == WEEKLY_COLUMNS


def test_missing_columns_and_duplicate_note_ids_are_rejected():
    scores, notes = make([("infobae", art(2024, 3, 5, 9), 0.1)])
    with pytest.raises(ValueError, match="scores lacks"):
        weekly_tone(scores.drop(columns="score"), notes)
    with pytest.raises(ValueError, match="duplicated note ids"):
        weekly_tone(scores, pd.concat([notes, notes]))


def test_duplicated_id_modelo_score_rows_are_rejected():
    scores, notes = make([("infobae", art(2024, 3, 5, 9), 0.1)])
    twice = pd.concat([scores, scores])
    with pytest.raises(ValueError, match=r"duplicated \(id, modelo\)"):
        weekly_tone(twice, notes)
    with pytest.raises(ValueError, match=r"duplicated \(id, modelo\)"):
        compare_milestones(twice, notes, hitos(("H", "2024-06-01", "nacional")))
    other_model = pd.concat([scores, scores.assign(modelo="otro")])
    assert len(weekly_tone(other_model, notes)) == 2  # the same note under two models is fine


def test_exclusions_count_each_dropped_row_once_by_first_matching_reason():
    rows = [("infobae", art(2024, 3, 5, 9), 0.1)] * 2  # kept
    rows += [("infobae", art(2024, 3, 5, 10), 0.1, True)] * 3  # live
    rows += [("infobae", art(2024, 3, 5, 11), math.nan)] * 4  # unparsed
    rows += [("infobae", art(2024, 3, 5, 12), 0.1)] * 5  # date removed below
    scores, notes = make(rows)
    notes.loc[notes.index[-5:], "fecha_publicacion"] = pd.NaT
    orphan = scores.iloc[:1].assign(id="sin-nota-1")
    scores = pd.concat([scores, orphan, orphan.assign(id="sin-nota-2")])
    assert tone_exclusions(scores, notes) == {"sin_nota": 2, "en_vivo": 3, "score_nan": 4, "sin_fecha": 5}
    assert weekly_tone(scores, notes)["n"].sum() == 2


def test_exclusions_are_all_zero_for_clean_input():
    scores, notes = make([("infobae", art(2024, 3, 5, 9), 0.1)])
    assert tone_exclusions(scores, notes) == {"sin_nota": 0, "en_vivo": 0, "score_nan": 0, "sin_fecha": 0}


def test_dataset_period_comes_from_the_scraping_definitions():
    from news_politica.defs.assets import PERIOD_END, PERIOD_START
    from news_politica.sentiment.tone import DATASET_END, DATASET_START

    assert (DATASET_START, DATASET_END) == (PERIOD_START, PERIOD_END)


def test_milestone_dates_are_normalized_to_midnight_art():
    scores, notes = make(spread("infobae", art(2024, 5, 1), 1, 40, 0.0))
    for written in ("2024-06-01", "2024-06-01 15:30", "2024-06-01T23:59:00-03:00", "2024-06-02T02:00:00+00:00"):
        (row,) = compare_milestones(scores, notes, hitos(("H", written, "nacional"))).to_dict("records")
        assert row["fecha"] == datetime(2024, 6, 1).date()
        assert row["n_antes"] == 14 and row["dias_antes"] == 14  # same windows as the plain date


def hitos(*rows):
    return pd.DataFrame(rows, columns=["hito", "fecha", "alcance"])


def spread(medio, start, per_day, days, score):
    """`per_day` notes a day for `days` days from `start`, all with `score`."""
    return [(medio, start + timedelta(days=d, hours=h), score) for d in range(days) for h in range(per_day)]


def test_dnu_window_is_clipped_and_flagged_truncated():
    # Dataset starts 2023-12-10: a 2023-12-21 milestone has 11 days before, one on the 20th has 10.
    rows = spread("infobae", art(2023, 12, 10), 2, 40, 0.1)
    out = compare_milestones(*make(rows), hitos(("DNU", "2023-12-21", "nacional"), ("DNU20", "2023-12-20", "nacional")))
    dnu, dnu20 = out.set_index("hito").loc["DNU"], out.set_index("hito").loc["DNU20"]
    assert (dnu["dias_antes"], dnu["dias_despues"], dnu["truncada"]) == (11, 14, True)
    assert dnu["n_antes"] == 22 and dnu["n_despues"] == 28
    assert dnu20["dias_antes"] == 10


def test_a_full_window_is_not_truncated_and_the_milestone_day_is_after():
    rows = spread("infobae", art(2024, 5, 1), 1, 40, 0.0)  # one note a day at 00:00, 05-01 .. 06-09
    rows += [("infobae", art(2024, 5, 31, 23, 59), -0.9)]  # one minute before the milestone: "before"
    (row,) = compare_milestones(*make(rows), hitos(("H", "2024-06-01", "nacional"))).to_dict("records")
    assert (row["dias_antes"], row["dias_despues"], row["truncada"]) == (14, 14, False)
    # before: days 05-18 .. 05-31 (14 notes) plus the 23:59 one; after: the 06-01 00:00 note counts, up to 06-14
    assert row["n_antes"] == 15 and row["n_despues"] == 9  # 06-01 .. 06-09 exist in the 40-day spread
    assert row["score_antes"] == pytest.approx((-0.9) / 15)


def test_enough_notes_report_means_shares_difference_and_welch_interval():
    before = [("infobae", art(2024, 5, 20) + timedelta(hours=i), s) for i, s in enumerate([-0.5, -0.1, -0.3, -0.7] * 3)]
    after = [("infobae", art(2024, 6, 2) + timedelta(hours=i), s) for i, s in enumerate([0.1, -0.1, 0.3, 0.5] * 3)]
    out = compare_milestones(*make(before + after), hitos(("H", "2024-06-01", "nacional")))
    (row,) = out.to_dict("records")
    assert (row["n_antes"], row["n_despues"], row["insuficiente"]) == (12, 12, False)
    assert row["score_antes"] == pytest.approx(-0.4) and row["score_despues"] == pytest.approx(0.2)
    assert row["diferencia"] == pytest.approx(0.6)
    assert row["prop_neg_antes"] == pytest.approx(0.75) and row["prop_neg_despues"] == 0.0
    var_b = pd.Series([-0.5, -0.1, -0.3, -0.7] * 3).var()
    var_a = pd.Series([0.1, -0.1, 0.3, 0.5] * 3).var()
    se = math.sqrt(var_b / 12 + var_a / 12)
    df = (var_b / 12 + var_a / 12) ** 2 / ((var_b / 12) ** 2 / 11 + (var_a / 12) ** 2 / 11)
    half = stats.t.ppf(0.975, df) * se
    assert (row["ic_sup"] - row["ic_inf"]) / 2 == pytest.approx(half)
    assert (row["ic_inf"] + row["ic_sup"]) / 2 == pytest.approx(0.6)


def test_a_side_below_the_minimum_is_insufficient_with_no_mean_or_share():
    before = spread("infobae", art(2024, 5, 20), 1, 12, -0.5)  # 12 notes
    after = spread("infobae", art(2024, 6, 2), 1, N_MIN - 1, 0.5)
    out = compare_milestones(*make(before + after), hitos(("H", "2024-06-01", "nacional")))
    (row,) = out.to_dict("records")
    assert row["insuficiente"] and row["n_despues"] == N_MIN - 1 and row["n_antes"] == 12
    assert math.isnan(row["score_despues"]) and math.isnan(row["prop_neg_despues"])
    assert row["score_antes"] == pytest.approx(-0.5) and row["prop_neg_antes"] == 1.0
    assert math.isnan(row["diferencia"]) and math.isnan(row["ic_inf"])


def test_an_outlet_without_notes_in_a_window_is_insufficient_with_n_zero():
    rows = spread("infobae", art(2024, 5, 20), 1, 30, 0.2) + [("lanacion", art(2024, 1, 1), 0.2)]
    out = compare_milestones(*make(rows), hitos(("H", "2024-06-01", "nacional")))
    la = out[out["medio"] == "lanacion"].iloc[0]
    assert (la["n_antes"], la["n_despues"], la["insuficiente"]) == (0, 0, True)


def test_milestone_without_a_date_is_left_out():
    scores, notes = make(spread("infobae", art(2024, 5, 20), 1, 30, 0.2))
    table = hitos(("Misiones", "", "misiones"), ("Otro", None, "nacional"), ("Real", "2024-06-01", "nacional"))
    out = compare_milestones(scores, notes, table)
    assert set(out["hito"]) == {"Real"}
    assert set(compare_milestones(scores, notes, hitos(("Misiones", "", "misiones")))["hito"]) == set()


def test_extra_milestone_columns_are_ignored_and_bad_dates_rejected():
    scores, notes = make(spread("infobae", art(2024, 5, 20), 1, 30, 0.2))
    table = hitos(("Real", "2024-06-01", "nacional")).assign(fuente="", verificado=False)
    assert len(compare_milestones(scores, notes, table)) == 1
    with pytest.raises(ValueError, match="invalid date"):
        compare_milestones(scores, notes, hitos(("Bad", "mañana", "nacional")))
    with pytest.raises(ValueError, match="lacks the column"):
        compare_milestones(scores, notes, table.drop(columns="alcance"))
    with pytest.raises(ValueError, match="n_min"):
        compare_milestones(scores, notes, table, n_min=1)


def test_live_notes_are_excluded_from_the_comparison():
    rows = spread("infobae", art(2024, 5, 20), 1, 30, 0.2)
    rows += [("infobae", art(2024, 5, 25, h), -0.9, True) for h in range(20)]
    (row,) = compare_milestones(*make(rows), hitos(("H", "2024-06-01", "nacional"))).to_dict("records")
    assert row["n_antes"] == 12 and row["score_antes"] == pytest.approx(0.2)


def test_committed_milestones_file_parses_and_claims_no_verified_date():
    from pathlib import Path

    table = pd.read_csv(Path(__file__).parents[2] / "anotaciones/hitos.csv", dtype=str, keep_default_na=False)
    assert list(table.columns) == ["hito", "fecha", "alcance", "fuente", "verificado"]
    assert len(table) == 4 and set(table["alcance"]) == {"nacional", "misiones"}
    assert set(table["verificado"]) == {"false"}  # task 8.1 (human) flips these after checking the sources
    assert table.loc[table["alcance"] == "misiones", "fecha"].item() == ""
    scores, notes = make(spread("infobae", art(2023, 12, 10), 1, 5, 0.2))
    compare_milestones(scores, notes, table)  # the file is readable by compare_milestones
