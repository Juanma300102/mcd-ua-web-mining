import logging
import math
from types import SimpleNamespace

import pytest
import requests

from news_politica.sentiment.classifiers import (
    MDEBERTA,
    OLLAMA_MODEL,
    QWEN,
    MdebertaClassifier,
    ModelUnavailable,
    OllamaClassifier,
    RobertuitoClassifier,
    SentimentModels,
    UnknownModel,
    _ollama_url,
)

URL = "http://ollama.test:11434"


class FakeResponse:
    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code

    def json(self):
        return self.body


class FakeOllamaSession:
    """Serves canned JSON by path. A route can be a FakeResponse, an exception or a list served in order."""

    def __init__(self, routes):
        self.routes = dict(routes)
        self.calls = []

    def _serve(self, method, url, **kwargs):
        path = url.removeprefix(URL)
        self.calls.append((method, path, kwargs))
        route = self.routes[path]
        if isinstance(route, list):
            route = route.pop(0) if len(route) > 1 else route[0]
        if isinstance(route, Exception):
            raise route
        return route

    def get(self, url, **kwargs):
        return self._serve("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._serve("POST", url, **kwargs)


def top(**digits):
    return [{"token": d, "logprob": lp} for d, lp in digits.items()]


def generated(answer, top_logprobs=None):
    body = {"response": answer}
    if top_logprobs is not None:
        body["logprobs"] = [{"token": answer.strip(), "logprob": -0.1, "top_logprobs": top_logprobs}]
    return FakeResponse(body)


def classifier_for(response):
    return OllamaClassifier(URL, FakeOllamaSession({"/api/generate": response}))


def test_logprobs_become_renormalized_probabilities():
    # P("3")=0.6, P("2")=0.3, P("1")=0.1 among the digits, plus a non-digit token
    tops = [
        {"token": "3", "logprob": math.log(0.5)},
        {"token": "2", "logprob": math.log(0.25)},
        {"token": "1", "logprob": math.log(0.0833333333)},
        {"token": "Positivo", "logprob": math.log(0.1)},
    ]
    (pos, neu, neg), = classifier_for(generated("3", tops)).predict(["texto"])
    assert pos == pytest.approx(0.6, abs=1e-6)
    assert neu == pytest.approx(0.3, abs=1e-6)
    assert neg == pytest.approx(0.1, abs=1e-6)
    assert pos + neu + neg == pytest.approx(1)


def test_logprobs_with_missing_digits_renormalize_over_the_present_ones():
    (probs,) = classifier_for(generated("2", top(**{"2": math.log(0.9), " 1": math.log(0.1)}))).predict(["x"])
    assert probs == pytest.approx((0.0, 0.9, 0.1))


def test_request_has_the_designed_options_and_prompt():
    session = FakeOllamaSession({"/api/generate": generated("2", top(**{"2": -0.1}))})
    OllamaClassifier(URL, session).predict(["Un texto"])
    method, path, kwargs = session.calls[0]
    assert (method, path) == ("POST", "/api/generate")
    payload = kwargs["json"]
    assert payload["model"] == OLLAMA_MODEL
    assert payload["stream"] is False
    assert payload["options"] == {"temperature": 0, "seed": 42, "num_predict": 2}
    assert payload["logprobs"] is True and payload["top_logprobs"] == 5
    assert "«Un texto»" in payload["prompt"]
    assert "1 = negativo, 2 = neutro, 3 = positivo" in payload["prompt"]


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("1", (0.0, 0.0, 1.0)), ("2", (0.0, 1.0, 0.0)), ("3", (1.0, 0.0, 0.0)), (" Es 3.", (1.0, 0.0, 0.0))],
)
def test_without_logprobs_the_digit_gives_one_hot(answer, expected):
    assert classifier_for(generated(answer)).predict(["x"]) == [expected]


def test_logprobs_without_any_digit_fall_back_to_one_hot():
    response = generated("1", [{"token": "Negativo", "logprob": -0.2}])
    assert classifier_for(response).predict(["x"]) == [(0.0, 0.0, 1.0)]


def token_entry(token, top_logprobs):
    return {"token": token, "logprob": -0.1, "top_logprobs": top_logprobs}


def test_weights_come_from_the_token_that_carries_the_digit():
    # First token is a space, the digit is in the second one: only the second one's alternatives count.
    body = {
        "response": " 3",
        "logprobs": [
            token_entry(" ", top(**{"1": math.log(0.9), "3": math.log(0.1)})),
            token_entry("3", top(**{"3": math.log(0.6), "2": math.log(0.4)})),
        ],
    }
    assert OllamaClassifier.parse(body) == pytest.approx((0.6, 0.4, 0.0))


def test_weights_come_from_the_token_after_a_word():
    body = {
        "response": "Es 1",
        "logprobs": [
            token_entry("Es", top(Es=-0.1)),
            token_entry(" 1", top(**{"1": math.log(0.5), "2": math.log(0.5)})),
        ],
    }
    assert OllamaClassifier.parse(body) == pytest.approx((0.0, 0.5, 0.5))


def test_digit_in_the_first_token_uses_it():
    body = {"response": "2", "logprobs": [token_entry("2", top(**{"2": math.log(0.8), "3": math.log(0.2)}))]}
    assert OllamaClassifier.parse(body) == pytest.approx((0.2, 0.8, 0.0))


def test_no_token_carrying_the_digit_gives_one_hot():
    body = {"response": "Es 3", "logprobs": [token_entry("Es", top(**{"1": -0.1, "3": -2.0}))]}
    assert OllamaClassifier.parse(body) == (1.0, 0.0, 0.0)


def test_no_logprobs_gives_one_hot_and_unparseable_gives_nan():
    assert OllamaClassifier.parse({"response": "1"}) == (0.0, 0.0, 1.0)
    assert all(math.isnan(p) for p in OllamaClassifier.parse({"response": "nada", "logprobs": [token_entry("nada", [])]}))


@pytest.mark.parametrize("answer", ["", "No sé", "cuatro"])
def test_unparseable_answer_gives_nan_probabilities(answer):
    (probs,) = classifier_for(generated(answer)).predict(["x"])
    assert len(probs) == 3 and all(math.isnan(p) for p in probs)


def test_generate_errors_raise_model_unavailable():
    down = classifier_for(requests.ConnectionError("refused"))
    with pytest.raises(ModelUnavailable, match="ollama serve"):
        down.predict(["x"])
    missing = classifier_for(FakeResponse({"error": "model not found"}, 404))
    with pytest.raises(ModelUnavailable, match="HTTP 404"):
        missing.predict(["x"])


def test_a_malformed_answer_for_one_note_is_nan_not_a_run_failure():
    session = FakeOllamaSession({"/api/generate": [generated("3", top(**{"3": -0.1})), generated("???"), generated("1")]})
    first, odd, last = OllamaClassifier(URL, session).predict(["a", "b", "c"])
    assert first[0] == 1.0 and last == (0.0, 0.0, 1.0)
    assert all(math.isnan(p) for p in odd)


@pytest.mark.parametrize(
    "logprobs",
    [
        [{"token": "3", "logprob": -0.1, "top_logprobs": 5}],
        [{"token": "3", "logprob": -0.1, "top_logprobs": "abc"}],
        [{"token": "3", "logprob": -0.1, "top_logprobs": [None, 7, "x"]}],
        [{"token": "3", "logprob": -0.1, "top_logprobs": [{"token": "3", "logprob": "high"}]}],
        [{"token": "3", "logprob": -0.1, "top_logprobs": [{"token": "3", "logprob": math.nan}]}],
        "garbage",
    ],
)
def test_ill_typed_logprobs_fall_back_to_one_hot(logprobs):
    assert OllamaClassifier.parse({"response": "3", "logprobs": logprobs}) == (1.0, 0.0, 0.0)


def test_non_dict_top_logprobs_entries_are_skipped():
    entries = [None, "x", *top(**{"3": -0.1, "2": -2.0})]
    probs = OllamaClassifier.parse({"response": "3", "logprobs": [token_entry("3", entries)]})
    assert probs[0] > 0.8 and probs[1] > 0 and probs[2] == 0


def test_programming_errors_in_parse_are_not_swallowed(monkeypatch):
    def broken(logprobs, digit):
        raise TypeError("bug")

    monkeypatch.setattr(OllamaClassifier, "_digit_weights", staticmethod(broken))
    with pytest.raises(TypeError, match="bug"):
        classifier_for(generated("3", top(**{"3": -0.1}))).predict(["x"])


@pytest.mark.parametrize("body", [{"model": "x"}, {"response": None}, {"response": 3}])
def test_a_body_without_a_response_text_raises_model_unavailable(body):
    with pytest.raises(ModelUnavailable, match="response"):
        classifier_for(FakeResponse(body)).predict(["x"])


def test_non_json_and_non_dict_bodies_share_one_guard():
    with pytest.raises(ModelUnavailable, match="non-JSON"):
        classifier_for(BadJson(None)).predict(["x"])
    with pytest.raises(ModelUnavailable, match="unexpected body"):
        classifier_for(FakeResponse([1])).predict(["x"])


def tags(*names):
    return FakeResponse({"models": [{"name": n} for n in names]})


def ps(size_vram=None):
    models = [] if size_vram is None else [{"name": OLLAMA_MODEL, "size_vram": size_vram}]
    return FakeResponse({"models": models})


def models_with(**routes):
    routes.setdefault("/api/generate", generated("2", top(**{"2": -0.1})))
    return SentimentModels(URL, FakeOllamaSession(routes))


def test_load_qwen_returns_an_ollama_classifier():
    loaded = models_with(**{"/api/tags": tags(OLLAMA_MODEL)}).load(QWEN)
    assert isinstance(loaded, OllamaClassifier)
    assert (loaded.name, loaded.device) == (QWEN, "ollama")


def test_load_qwen_with_ollama_down_raises():
    models = models_with(**{"/api/tags": requests.ConnectionError("refused")})
    with pytest.raises(ModelUnavailable, match="ollama serve"):
        models.load(QWEN)


def test_load_qwen_with_model_not_pulled_raises():
    models = models_with(**{"/api/tags": tags("llama3:8b")})
    with pytest.raises(ModelUnavailable, match=f"ollama pull {OLLAMA_MODEL}"):
        models.load(QWEN)


def test_unknown_model_name_is_rejected():
    with pytest.raises(UnknownModel, match="unknown sentiment model"):
        models_with().load("gpt")


def test_alternative_picks_qwen_when_ollama_uses_the_gpu():
    models = models_with(**{"/api/tags": tags(OLLAMA_MODEL), "/api/ps": ps(4_700_000_000)})
    assert models.alternative() == QWEN
    paths = [path for _, path, _ in models.session.calls]
    assert paths.index("/api/generate") < paths.index("/api/ps")  # warm-up before asking /api/ps


def test_alternative_falls_back_when_size_vram_is_zero(caplog):
    models = models_with(**{"/api/tags": tags(OLLAMA_MODEL), "/api/ps": ps(0)})
    with caplog.at_level(logging.WARNING):
        assert models.alternative() == MDEBERTA
    assert "size_vram is 0" in caplog.text


@pytest.mark.parametrize("size", [math.nan, math.inf, -math.inf])
def test_non_finite_size_vram_is_model_unavailable(size):
    models = models_with(**{"/api/tags": tags(OLLAMA_MODEL), "/api/ps": FakeResponse({"models": [{"name": OLLAMA_MODEL, "size_vram": size}]})})
    with pytest.raises(ModelUnavailable, match="size_vram"):
        models._vram_bytes()
    assert models.alternative() == MDEBERTA


def test_alternative_falls_back_when_the_model_is_not_listed_as_running():
    models = models_with(**{"/api/tags": tags(OLLAMA_MODEL), "/api/ps": ps(None)})
    assert models.alternative() == MDEBERTA


def test_alternative_falls_back_when_ollama_is_down(caplog):
    models = models_with(**{"/api/tags": requests.ConnectionError("refused")})
    with caplog.at_level(logging.WARNING):
        assert models.alternative() == MDEBERTA
    assert "not reachable" in caplog.text


def test_alternative_falls_back_when_the_model_is_not_pulled():
    assert models_with(**{"/api/tags": tags()}).alternative() == MDEBERTA


class BadJson(FakeResponse):
    def json(self):
        raise ValueError("Expecting value")


@pytest.mark.parametrize(
    "routes",
    [
        {"/api/tags": BadJson(None)},
        {"/api/tags": FakeResponse(["not", "a", "dict"])},
        {"/api/tags": FakeResponse({"models": "none"})},
        {"/api/tags": FakeResponse({"models": ["x"]})},
        {"/api/tags": tags(OLLAMA_MODEL), "/api/generate": BadJson(None)},
        {"/api/tags": tags(OLLAMA_MODEL), "/api/generate": FakeResponse([1])},
        {"/api/tags": tags(OLLAMA_MODEL), "/api/generate": FakeResponse({"response": 3})},
        {"/api/tags": tags(OLLAMA_MODEL), "/api/generate": FakeResponse({"error": "no response field"})},
        {"/api/tags": tags(OLLAMA_MODEL), "/api/generate": requests.Timeout("slow")},
        {"/api/tags": tags(OLLAMA_MODEL), "/api/ps": BadJson(None)},
        {"/api/tags": tags(OLLAMA_MODEL), "/api/ps": FakeResponse({"models": {"a": 1}})},
        {"/api/tags": tags(OLLAMA_MODEL), "/api/ps": FakeResponse({"models": [{"name": OLLAMA_MODEL, "size_vram": "big"}]})},
        {"/api/tags": tags(OLLAMA_MODEL), "/api/ps": FakeResponse({"models": [{"name": OLLAMA_MODEL, "size_vram": [1]}]})},
        {"/api/tags": tags(OLLAMA_MODEL), "/api/ps": requests.ReadTimeout("slow")},
    ],
)
def test_alternative_falls_back_on_any_failure_to_establish_the_llm(routes, caplog):
    models = models_with(**routes)
    with caplog.at_level(logging.WARNING):
        assert models.alternative() == MDEBERTA
    assert "Using mdeberta-xnli" in caplog.text


def test_explicit_qwen_still_fails_on_a_malformed_body():
    with pytest.raises(ModelUnavailable):
        models_with(**{"/api/tags": BadJson(None)}).load(QWEN)


@pytest.mark.parametrize("name", ["robertuito", MDEBERTA])
def test_torch_models_without_the_sentiment_group_raise_model_unavailable(name):
    try:
        import torch  # noqa: F401
    except ImportError:
        with pytest.raises(ModelUnavailable, match="uv sync --group sentiment"):
            SentimentModels(URL, FakeOllamaSession({})).load(name)
    else:
        pytest.skip("torch is installed")


def test_robertuito_maps_probas_to_pos_neu_neg():
    outputs = [SimpleNamespace(probas={"NEG": 0.5, "NEU": 0.3, "POS": 0.2})]
    analyzer = SimpleNamespace(predict=lambda texts: outputs)
    classifier = RobertuitoClassifier(analyzer=analyzer, device="cpu")
    assert classifier.predict(["x"]) == [(0.2, 0.3, 0.5)]
    assert (classifier.name, classifier.device) == ("robertuito", "cpu")


def test_mdeberta_maps_scores_by_label_and_passes_the_designed_arguments():
    calls = []

    def pipe(texts, **kwargs):
        calls.append(kwargs)
        return [
            {"sequence": t, "labels": ["negativo", "positivo", "neutro"], "scores": [0.6, 0.3, 0.1]}
            for t in texts
        ]

    classifier = MdebertaClassifier(pipeline=pipe, device="cpu")
    assert classifier.predict(["a", "b"]) == [(0.3, 0.1, 0.6)] * 2
    assert calls[0] == {
        "candidate_labels": ["positivo", "neutro", "negativo"],
        "hypothesis_template": "El tono de esta noticia es {}.",
        "multi_label": False,
        "batch_size": 16,
        "truncation": True,
    }


def test_ollama_host_without_scheme_gets_one(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11434/")
    assert _ollama_url() == "http://127.0.0.1:11434"
    monkeypatch.delenv("OLLAMA_HOST")
    assert _ollama_url() == "http://localhost:11434"
