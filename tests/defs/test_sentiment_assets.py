import math
import subprocess
import sys

import dagster as dg
import pandas as pd
import pytest
from upath import UPath

from news_politica.defs.io import ParquetIOManager
from news_politica.defs.sentiment import MODELO_FINAL, ScoringConfig, sentimiento_noticias
from news_politica.sentiment.classifiers import ModelUnavailable, SentimentModels
from news_politica.sentiment.scoring import SCORE_COLUMNS

from .conftest import UPSTREAM, info_logs, metadata, store

ALL = [*UPSTREAM, sentimiento_noticias]


class FakeClassifier:
    device = "cpu"

    def __init__(self, name):
        self.name = name

    def predict(self, texts):
        out = []
        for text in texts:
            if "bien" in text:
                out.append((0.7, 0.2, 0.1))
            elif "mal" in text:
                out.append((0.1, 0.2, 0.7))
            elif "raro" in text:
                out.append((math.nan,) * 3)
            else:
                out.append((0.2, 0.6, 0.2))
        return out


class FakeModels:
    """Stands in for `SentimentModels`: no torch, no Ollama."""

    def __init__(self, unavailable=(), fail_midrun=()):
        self.unavailable = set(unavailable)
        self.fail_midrun = set(fail_midrun)
        self.loaded = []

    def load(self, name):
        if name in self.unavailable:
            raise ModelUnavailable(f"{name} needs `uv sync --group sentiment`")
        self.loaded.append(name)
        classifier = FakeClassifier(name)
        if name in self.fail_midrun:
            def predict(texts):
                raise ModelUnavailable("Ollama is not reachable; run `ollama serve`")
            classifier.predict = predict
        return classifier


def make_notes(titles):
    return pd.DataFrame({
        "id": [f"n{i}" for i in range(len(titles))],
        "titulo": titles,
        "bajada": "Bajada.",
        "cuerpo": "Cuerpo.",
        "medio": "infobae",
    })


def run(tmp_path, client, models, modelos=None, instance=None):
    config = {"ops": {"sentimiento_noticias": {"config": {"modelos": modelos}}}} if modelos else None
    resources = {"io_manager": ParquetIOManager(base_path=UPath(tmp_path)), "client": client,
                 "sentiment_models": models}
    return dg.materialize(ALL, selection=[sentimiento_noticias], resources=resources, run_config=config,
                          instance=instance, raise_on_error=False)


def test_one_row_per_note_and_model(tmp_path, client):
    store(tmp_path, "noticias_politica", make_notes(["todo bien", "todo mal", "raro", "nada"]))
    models = FakeModels()
    result = run(tmp_path, client, models, ["robertuito", "mdeberta-xnli"])
    assert result.success
    scores = result.output_for_node("sentimiento_noticias")
    assert list(scores.columns) == SCORE_COLUMNS
    assert len(scores) == 8 and not scores.duplicated(["id", "modelo"]).any()
    assert models.loaded == ["robertuito", "mdeberta-xnli"]
    one = scores[scores["modelo"] == "robertuito"].set_index("id")
    assert one.loc["n0", "score"] == pytest.approx(0.6) and one.loc["n0", "label"] == "pos"
    assert one.loc["n1", "score"] == pytest.approx(-0.6) and one.loc["n1", "label"] == "neg"
    assert one.loc["n2", "label"] is None and math.isnan(one.loc["n2", "score"])
    assert one[["prob_pos", "prob_neu", "prob_neg"]].dropna().sum(axis=1).tolist() == pytest.approx([1, 1, 1])


def test_metadata_and_default_model(tmp_path, client):
    store(tmp_path, "noticias_politica", make_notes(["todo bien", "todo mal", "raro"]))
    result = run(tmp_path, client, FakeModels())
    assert result.success
    assert metadata(result, "sentimiento_noticias") == {
        "rows": 3,
        "rows_per_modelo": {MODELO_FINAL: 3},
        "labels": {MODELO_FINAL: {"pos": 1, "neg": 1}},
        "unparsed": 1,
    }


def test_the_source_dataset_is_not_modified(tmp_path, client):
    store(tmp_path, "noticias_politica", make_notes(["todo bien", "nada"]))
    source = tmp_path / "noticias_politica.parquet"
    before = source.read_bytes()
    assert run(tmp_path, client, FakeModels()).success
    assert source.read_bytes() == before
    assert (tmp_path / "sentimiento_noticias.parquet").exists()


def test_unavailable_model_is_a_non_retryable_failure(tmp_path, client):
    store(tmp_path, "noticias_politica", make_notes(["todo bien"]))
    result = run(tmp_path, client, FakeModels(unavailable={"robertuito"}), ["robertuito"])
    assert not result.success
    assert not (tmp_path / "sentimiento_noticias.parquet").exists()
    # Called directly, the failure carries allow_retries=False, so a retry policy would not apply.
    with pytest.raises(dg.Failure, match="uv sync --group sentiment") as caught:
        sentimiento_noticias(
            dg.build_asset_context(), ScoringConfig(modelos=["robertuito"]),
            FakeModels(unavailable={"robertuito"}), make_notes(["todo bien"]),
        )
    assert caught.value.allow_retries is False


def test_model_lost_mid_run_is_a_non_retryable_failure_naming_the_model(tmp_path, client):
    store(tmp_path, "noticias_politica", make_notes(["todo bien"]))
    assert not run(tmp_path, client, FakeModels(fail_midrun={"qwen2.5-7b"}), ["qwen2.5-7b"]).success
    with pytest.raises(dg.Failure, match="qwen2.5-7b became unavailable while scoring.*ollama serve") as caught:
        sentimiento_noticias(
            dg.build_asset_context(), ScoringConfig(modelos=["qwen2.5-7b"]),
            FakeModels(fail_midrun={"qwen2.5-7b"}), make_notes(["todo bien"]),
        )
    assert caught.value.allow_retries is False


def test_unknown_model_name_is_a_non_retryable_failure():
    with pytest.raises(dg.Failure, match="unknown sentiment model") as caught:
        sentimiento_noticias(
            dg.build_asset_context(), ScoringConfig(modelos=["gpt"]), SentimentModels(session=object()),
            make_notes(["todo bien"]),
        )
    assert caught.value.allow_retries is False


def test_unrelated_value_errors_are_not_converted_to_failures():
    class Broken(FakeModels):
        def load(self, name):
            raise ValueError("a programming error")

    with pytest.raises(ValueError, match="programming error"):
        sentimiento_noticias(
            dg.build_asset_context(), ScoringConfig(modelos=["robertuito"]), Broken(), make_notes(["todo bien"])
        )


def test_duplicate_models_are_dropped_keeping_order(tmp_path, client):
    assert ScoringConfig(modelos=["b", "a", "b", "a"]).modelos == ["b", "a"]
    store(tmp_path, "noticias_politica", make_notes(["todo bien", "nada"]))
    models = FakeModels()
    result = run(tmp_path, client, models, ["robertuito", "mdeberta-xnli", "robertuito"])
    assert result.success
    scores = result.output_for_node("sentimiento_noticias")
    assert len(scores) == 4 and not scores.duplicated(["id", "modelo"]).any()
    assert models.loaded == ["robertuito", "mdeberta-xnli"]


def test_logs_start_progress_and_summary(tmp_path, client):
    store(tmp_path, "noticias_politica", make_notes(["todo bien"] * 800))  # 25 batches of 32
    with dg.DagsterInstance.ephemeral() as instance:
        result = run(tmp_path, client, FakeModels(), ["robertuito"], instance)
        assert result.success
        logs = info_logs(instance, result)
    assert "scoring 800 notes with robertuito" in logs[0]
    progress = [m for m in logs if m.endswith("notes scored") and "/" in m]
    assert [m.split()[1] for m in progress] == ["320/800", "640/800"]
    assert any("robertuito: 800 notes scored (0 neg, 0 neu, 800 pos, 0 unparsed)" in m for m in logs)
    assert "800 rows scored" in logs[-1]


def test_definitions_load_without_torch():
    code = (
        "import sys\n"
        "from news_politica.definitions import defs\n"
        "defs()\n"
        "assert 'torch' not in sys.modules and 'transformers' not in sys.modules, 'torch was imported'\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
