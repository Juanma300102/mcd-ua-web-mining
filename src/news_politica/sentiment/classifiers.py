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
import time
from collections.abc import Callable
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
OLLAMA_PROBE_TIMEOUT = 10
OLLAMA_ATTEMPTS = 3  # tries per request when the failure is transient
OLLAMA_BACKOFF_S = 0.5  # sleep before the 2nd try; doubles before each later one
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


class UnknownModel(ValueError):
    """The requested model name is not one of `MODEL_NAMES`."""


def _json_object(response, where: str) -> dict:
    """The JSON object of an Ollama answer; anything else is a server-level failure."""
    try:
        body = response.json()
    except ValueError as exc:
        raise ModelUnavailable(f"Ollama answered a non-JSON body {where} ({exc})") from exc
    if not isinstance(body, dict):
        raise ModelUnavailable(f"Ollama answered an unexpected body {where}")
    return body


def _finite_number(value) -> float | None:
    """`value` as a finite float, or None for bools, non-numbers, NaN, infinities and ints too big for a float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _call_ollama(
    send: Callable[[], requests.Response], where: str, sleep: Callable[[float], None], hint: str = ""
) -> requests.Response:
    """Run one Ollama request under the error policy shared by every call to the server.

    Transient failures (timeouts, connection errors, HTTP 429 and 5xx) are retried up to
    `OLLAMA_ATTEMPTS` times with a doubling backoff, then raise `ModelUnavailable`. Anything else
    (other 4xx, other transport errors) raises `ModelUnavailable` at once: retrying cannot fix it.
    Bodies are checked by the callers, and a bad body is never retried.
    """
    reason = ""
    for attempt in range(OLLAMA_ATTEMPTS):
        try:
            response = send()
        except (requests.Timeout, requests.ConnectionError) as exc:
            reason = f"Ollama is not reachable {where}; run `ollama serve` ({exc})"
        except requests.RequestException as exc:
            raise ModelUnavailable(f"Ollama request failed {where} ({exc})") from exc
        else:
            code = response.status_code
            if code == 200:
                return response
            reason = f"Ollama answered HTTP {code} {where}{hint}"
            if code != 429 and code < 500:
                raise ModelUnavailable(reason)
        if attempt < OLLAMA_ATTEMPTS - 1:
            sleep(OLLAMA_BACKOFF_S * 2**attempt)
    raise ModelUnavailable(f"{reason} (gave up after {OLLAMA_ATTEMPTS} attempts)")


class Classifier(Protocol):
    name: str  # the `modelo` value
    device: str  # "cpu", "cuda" or "ollama"

    def predict(self, texts: list[str]) -> list[Probs]: ...


class OllamaClassifier:
    """Qwen through Ollama's `/api/generate`, one request per text.

    The model answers with a digit (1 negative, 2 neutral, 3 positive). When the
    response carries logprobs, the probabilities are the renormalized `exp(logprob)`
    of the digits among the `top_logprobs` of the token that carries the answer digit; otherwise the parsed
    digit gives a one-hot. An unparseable answer gives NaN probabilities.
    """

    name = QWEN
    device = "ollama"

    def __init__(self, url: str = OLLAMA_URL, session=None, model: str = OLLAMA_MODEL, sleep=time.sleep):
        self.url = url.rstrip("/")
        self.session = session or requests.Session()
        self.model = model
        self.sleep = sleep  # injected in tests so retries never really wait

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
        where = f"at {self.url}/api/generate"
        response = _call_ollama(
            lambda: self.session.post(f"{self.url}/api/generate", json=payload, timeout=OLLAMA_TIMEOUT),
            where,
            self.sleep,
            hint=f"; {OLLAMA_PULL_HINT} if the model is missing",
        )
        body = _json_object(response, f"at {self.url}/api/generate")
        if not isinstance(body.get("response"), str):
            raise ModelUnavailable(f"Ollama answered without a `response` text at {self.url}/api/generate")
        # Only transport/server-level failures raise above. From here on a single odd answer is
        # that note's problem: `parse` returns NaN probabilities and the note counts as unparsed.
        return self.parse(body)

    @staticmethod
    def parse(body: dict) -> Probs:
        """Probabilities of one answer. Every field is type-checked: a malformed answer is NaN.

        Wrong-typed `response`, `logprobs`, `top_logprobs`, entries, `token` or `logprob` never
        raise; they degrade to one-hot (the digit is readable) or NaN (it is not). Only real
        programming errors propagate.
        """
        response = body.get("response")
        found = re.search(r"[123]", response) if isinstance(response, str) else None
        if not found:
            return NAN_PROBS
        digit = found.group()
        weights = OllamaClassifier._digit_weights(body.get("logprobs"), digit)
        if not weights:
            return DIGIT_TO_PROBS[digit]
        total = sum(weights.values())
        probs = [0.0, 0.0, 0.0]
        for d, weight in weights.items():
            probs[DIGIT_INDEX[d]] = weight / total
        return (probs[0], probs[1], probs[2])

    @staticmethod
    def _token(entry) -> str | None:
        """The stripped `token` of a logprobs entry, or None when the entry or its token is ill-typed."""
        if not isinstance(entry, dict) or not isinstance(entry.get("token"), str):
            return None
        return entry["token"].strip()

    @staticmethod
    def _digit_weights(logprobs, digit: str) -> dict[str, float]:
        """`exp(logprob)` of the digits in the `top_logprobs` of the token that carries the answer digit.

        The model may emit a space or a word before the digit, so the first generated token is not
        always the one that holds the answer. Entries, tokens and logprobs of the wrong type are skipped.
        """
        if not isinstance(logprobs, list):
            return {}
        entry = next((e for e in logprobs if OllamaClassifier._token(e) == digit), None)
        candidates = entry.get("top_logprobs") if entry else None
        if not isinstance(candidates, list):
            return {}
        weights: dict[str, float] = {}
        for candidate in candidates:
            token = OllamaClassifier._token(candidate)
            value = _finite_number(candidate.get("logprob")) if token is not None else None
            if token in DIGIT_TO_PROBS and token not in weights and value is not None:
                weights[token] = math.exp(min(value, 0.0))  # a logprob is <= 0; clamping avoids overflow
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

    def __init__(self, ollama_url: str = OLLAMA_URL, session=None, sleep=time.sleep):
        self.ollama_url = ollama_url.rstrip("/")
        self.session = session or requests.Session()
        self.sleep = sleep  # injected in tests so retries never really wait

    def load(self, name: str) -> Classifier:
        if name == ROBERTUITO:
            return RobertuitoClassifier()
        if name == MDEBERTA:
            return MdebertaClassifier()
        if name == QWEN:
            self._require_ollama_model()
            return OllamaClassifier(self.ollama_url, self.session, sleep=self.sleep)
        raise UnknownModel(f"unknown sentiment model {name!r}; choose one of {list(MODEL_NAMES)}")

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
        where = f"for {path} at {self.ollama_url}"
        response = _call_ollama(
            lambda: self.session.get(f"{self.ollama_url}{path}", timeout=OLLAMA_PROBE_TIMEOUT), where, self.sleep
        )
        return _json_object(response, f"for {path} at {self.ollama_url}")

    def _models(self, path: str) -> list[dict]:
        models = self._get(path).get("models", [])
        if not isinstance(models, list) or not all(isinstance(m, dict) for m in models):
            raise ModelUnavailable(f"Ollama answered an unexpected `models` shape for {path} at {self.ollama_url}")
        return models

    def _require_ollama_model(self) -> None:
        names = {m.get("name") or m.get("model") for m in self._models("/api/tags")}
        if OLLAMA_MODEL not in names:
            raise ModelUnavailable(f"Ollama has no model {OLLAMA_MODEL}; {OLLAMA_PULL_HINT}")

    def _vram_bytes(self) -> int:
        for model in self._models("/api/ps"):
            if (model.get("name") or model.get("model")) == OLLAMA_MODEL:
                size = model.get("size_vram")
                if size is None:
                    return 0
                number = _finite_number(size)  # also rejects ints too big for a float (OverflowError)
                if number is None:
                    raise ModelUnavailable(f"Ollama reported an invalid size_vram at {self.ollama_url}: {size!r:.40}")
                return int(number)
        return 0
