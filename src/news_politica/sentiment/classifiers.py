"""Sentiment classifiers and the model resource.

Every classifier returns `(pos, neu, neg)` probabilities per text. torch,
transformers and pysentimiento are imported only inside methods, so importing
this module (and loading the Dagster definitions) never needs the `sentiment`
dependency group. The local LLM runs inside Ollama and is reached over HTTP with
`requests`, so it adds no Python package.
"""

from __future__ import annotations

import logging
import math
import os
import re
from typing import Protocol

import requests

log = logging.getLogger(__name__)

Probs = tuple[float, float, float]  # (pos, neu, neg); sums to 1, or all NaN when unparsed
NAN_PROBS: Probs = (math.nan, math.nan, math.nan)

ROBERTUITO = "robertuito"
MDEBERTA = "mdeberta-xnli"
QWEN = "qwen2.5-7b"
MODEL_NAMES = (ROBERTUITO, MDEBERTA, QWEN)

OLLAMA_MODEL = "qwen2.5:7b-instruct"
MDEBERTA_CHECKPOINT = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
MDEBERTA_LABELS = ("positivo", "neutro", "negativo")  # (pos, neu, neg)
MDEBERTA_HYPOTHESIS = "El tono de esta noticia es {}."
MDEBERTA_BATCH_SIZE = 16

SYSTEM_PROMPT = (
    "Clasificas el tono (valencia) de textos de noticias políticas argentinas. "
    "No evalúas la postura hacia el gobierno, solo si el texto es negativo, neutro o positivo."
)
USER_PROMPT = "Texto: «{texto}»\nResponde solo con un número: 1 = negativo, 2 = neutro, 3 = positivo."
DIGIT_TO_PROBS: dict[str, Probs] = {"1": (0.0, 0.0, 1.0), "2": (0.0, 1.0, 0.0), "3": (1.0, 0.0, 0.0)}
DIGIT_INDEX = {"1": 2, "2": 1, "3": 0}  # position of each digit's class in (pos, neu, neg)

OLLAMA_TIMEOUT = 120
OLLAMA_OPTIONS = {"temperature": 0, "seed": 42, "num_predict": 2}
OLLAMA_PULL_HINT = f"run `ollama pull {OLLAMA_MODEL}`"
SYNC_HINT = "run `uv sync --group sentiment`"


def _ollama_url(value: str | None = None) -> str:
    """`OLLAMA_HOST` may omit the scheme (Ollama itself accepts `127.0.0.1:11434`)."""
    url = (value or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").strip().rstrip("/")
    return url if "://" in url else f"http://{url}"


OLLAMA_URL = _ollama_url()


class ModelUnavailable(RuntimeError):
    """A model cannot be used on this machine; the message says how to fix it."""


class Classifier(Protocol):
    name: str  # the `modelo` value
    device: str  # "cpu", "cuda" or "ollama"

    def predict(self, texts: list[str]) -> list[Probs]: ...


class OllamaClassifier:
    """Qwen through Ollama's `/api/generate`, one request per text.

    The model answers with a digit (1 negative, 2 neutral, 3 positive). When the
    response carries logprobs, the probabilities are the renormalized `exp(logprob)`
    of the digits among the first token's `top_logprobs`; otherwise the parsed
    digit gives a one-hot. An unparseable answer gives NaN probabilities.
    """

    name = QWEN
    device = "ollama"

    def __init__(self, url: str = OLLAMA_URL, session=None, model: str = OLLAMA_MODEL):
        self.url = url.rstrip("/")
        self.session = session or requests.Session()
        self.model = model

    def predict(self, texts: list[str]) -> list[Probs]:
        return [self._predict_one(text) for text in texts]

    def _predict_one(self, text: str) -> Probs:
        payload = {
            "model": self.model,
            "system": SYSTEM_PROMPT,
            "prompt": USER_PROMPT.format(texto=text),
            "stream": False,
            "options": OLLAMA_OPTIONS,
            "logprobs": True,
            "top_logprobs": 5,
        }
        try:
            response = self.session.post(f"{self.url}/api/generate", json=payload, timeout=OLLAMA_TIMEOUT)
        except requests.RequestException as exc:
            raise ModelUnavailable(f"Ollama is not reachable at {self.url}; run `ollama serve` ({exc})") from exc
        if response.status_code != 200:
            raise ModelUnavailable(
                f"Ollama answered HTTP {response.status_code} at {self.url}/api/generate; {OLLAMA_PULL_HINT} "
                "if the model is missing"
            )
        return self.parse(response.json())

    @staticmethod
    def parse(body: dict) -> Probs:
        found = re.search(r"[123]", body.get("response") or "")
        if not found:
            return NAN_PROBS
        digit = found.group()
        weights = OllamaClassifier._digit_weights(body.get("logprobs"))
        if not weights:
            return DIGIT_TO_PROBS[digit]
        total = sum(weights.values())
        probs = [0.0, 0.0, 0.0]
        for d, weight in weights.items():
            probs[DIGIT_INDEX[d]] = weight / total
        return (probs[0], probs[1], probs[2])

    @staticmethod
    def _digit_weights(logprobs) -> dict[str, float]:
        """`exp(logprob)` of the digits in the first generated token's `top_logprobs`."""
        if not logprobs:
            return {}
        weights: dict[str, float] = {}
        for candidate in logprobs[0].get("top_logprobs") or []:
            token = str(candidate.get("token", "")).strip()
            value = candidate.get("logprob")
            if token in DIGIT_TO_PROBS and token not in weights and value is not None:
                weights[token] = math.exp(value)
        return weights if sum(weights.values()) > 0 else {}


class RobertuitoClassifier:
    """`pysentimiento/robertuito-sentiment-analysis` through pysentimiento (spike verdict, task 1.2).

    `analyzer` can be injected for tests; otherwise it is created on first use.
    """

    name = ROBERTUITO

    def __init__(self, analyzer=None, device: str | None = None):
        if analyzer is None:
            try:
                import torch
                from pysentimiento import create_analyzer
            except ImportError as exc:
                raise ModelUnavailable(f"torch or pysentimiento is not installed; {SYNC_HINT}") from exc
            device = device or ("cuda" if torch.cuda.is_available() else "cpu")
            analyzer = create_analyzer(task="sentiment", lang="es")
        self.analyzer = analyzer
        self.device = device or "cpu"
        log.info("%s: loaded on %s", self.name, self.device)

    def predict(self, texts: list[str]) -> list[Probs]:
        outputs = self.analyzer.predict(list(texts))
        if not isinstance(outputs, list):
            outputs = [outputs]
        return [(o.probas["POS"], o.probas["NEU"], o.probas["NEG"]) for o in outputs]


class MdebertaClassifier:
    """mDeBERTa XNLI zero-shot: entailment of "El tono de esta noticia es {positivo|neutro|negativo}."

    `pipeline` can be injected for tests; otherwise it is built on first use.
    """

    name = MDEBERTA

    def __init__(self, pipeline=None, device: str | None = None):
        if pipeline is None:
            try:
                import torch
                from transformers import pipeline as make_pipeline
            except ImportError as exc:
                raise ModelUnavailable(f"torch or transformers is not installed; {SYNC_HINT}") from exc
            device = device or ("cuda" if torch.cuda.is_available() else "cpu")
            pipeline = make_pipeline(
                "zero-shot-classification",
                model=MDEBERTA_CHECKPOINT,
                device=0 if device == "cuda" else -1,
            )
        self.pipeline = pipeline
        self.device = device or "cpu"
        log.info("%s: loaded on %s", self.name, self.device)

    def predict(self, texts: list[str]) -> list[Probs]:
        results = self.pipeline(
            list(texts),
            candidate_labels=list(MDEBERTA_LABELS),
            hypothesis_template=MDEBERTA_HYPOTHESIS,
            multi_label=False,
            batch_size=MDEBERTA_BATCH_SIZE,
            truncation=True,
        )
        if isinstance(results, dict):
            results = [results]
        out = []
        for result in results:
            by_label = dict(zip(result["labels"], result["scores"], strict=True))
            out.append(tuple(float(by_label[label]) for label in MDEBERTA_LABELS))
        return out


class SentimentModels:
    """Plain resource that builds classifiers on demand and picks the alternative model."""

    def __init__(self, ollama_url: str = OLLAMA_URL, session=None):
        self.ollama_url = ollama_url.rstrip("/")
        self.session = session or requests.Session()

    def load(self, name: str) -> Classifier:
        if name == ROBERTUITO:
            return RobertuitoClassifier()
        if name == MDEBERTA:
            return MdebertaClassifier()
        if name == QWEN:
            self._require_ollama_model()
            return OllamaClassifier(self.ollama_url, self.session)
        raise ValueError(f"unknown sentiment model {name!r}; choose one of {list(MODEL_NAMES)}")

    def alternative(self) -> str:
        """`qwen2.5-7b` only if Ollama serves it from the GPU (`size_vram > 0`), else `mdeberta-xnli`."""
        try:
            classifier = self.load(QWEN)
            classifier.predict(["Hola"])  # warm-up so /api/ps lists the loaded model
            if self._vram_bytes() > 0:
                return QWEN
            reason = "Ollama runs the model on CPU (size_vram is 0)"
        except ModelUnavailable as exc:
            reason = str(exc)
        log.warning("Using %s instead of %s: %s", MDEBERTA, QWEN, reason)
        return MDEBERTA

    def _get(self, path: str) -> dict:
        try:
            response = self.session.get(f"{self.ollama_url}{path}", timeout=10)
        except requests.RequestException as exc:
            raise ModelUnavailable(f"Ollama is not reachable at {self.ollama_url}; run `ollama serve` ({exc})") from exc
        if response.status_code != 200:
            raise ModelUnavailable(f"Ollama answered HTTP {response.status_code} for {path} at {self.ollama_url}")
        return response.json()

    def _require_ollama_model(self) -> None:
        names = {m.get("name") or m.get("model") for m in self._get("/api/tags").get("models", [])}
        if OLLAMA_MODEL not in names:
            raise ModelUnavailable(f"Ollama has no model {OLLAMA_MODEL}; {OLLAMA_PULL_HINT}")

    def _vram_bytes(self) -> int:
        for model in self._get("/api/ps").get("models", []):
            if (model.get("name") or model.get("model")) == OLLAMA_MODEL:
                return int(model.get("size_vram") or 0)
        return 0
