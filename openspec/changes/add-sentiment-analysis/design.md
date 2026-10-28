# Design: Sentiment analysis of political news (Phase 5)

## Technical Approach

Pure, torch-free logic lives in a new `src/news_politica/sentiment/` package. A thin Dagster layer in `src/news_politica/defs/sentiment.py` wraps it as two unpartitioned assets, `sentimiento_noticias` and `evolucion_tono`, following the `dagster-assets` conventions: plain `@dg.asset` functions returning DataFrames through `ParquetIOManager`, INFO start/progress/summary lines, and a plain object resource typed `dg.ResourceParam[...]`, like `PoliteClient`. Every model import (torch, transformers, pysentimiento) happens inside `SentimentModels.load()`, so `uv run pytest` and `uv run dg check defs` run without the `sentiment` group. Tests inject a fake model loader. The labeling sample, label merge, model evaluation and before/after comparison are pure functions that the notebook calls. They are not assets, so the asset graph stays at the two assets the proposal names.

## Architecture Decisions

### 1. Module layout

**Choice**:

| Module | Contents |
|---|---|
| `sentiment/text.py` | `analysis_text` (the model input and which field it came from) |
| `sentiment/classifiers.py` | `Classifier` protocol, the three model wrappers, `SentimentModels` (loader and hardware detection), `ModelUnavailable` |
| `sentiment/scoring.py` | `score_notes`: batches the texts, builds the long frame, logs progress |
| `sentiment/labeling.py` | `labeling_sample`, `export_sheets`, `read_labels` |
| `sentiment/evaluation.py` | macro F1 and confusion matrix, written in pandas |
| `sentiment/tone.py` | `weekly_tone` and `compare_milestones` |
| `defs/sentiment.py` | the two assets and `ScoringConfig` |
| `defs/io.py` | registers the `sentiment_models` resource |

**Alternatives considered**: putting the assets in `defs/assets.py` (its docstring and scope are Phase 4); one large `sentiment.py` module (mixes I/O-free logic with model loading).
**Rationale**: this matches the existing `sources/` (pure) and `defs/` (Dagster) split. Only `classifiers.py` touches model libraries, and only inside methods.

### 2. Model resource with lazy imports

**Choice**: `SentimentModels` is a plain class registered in `defs/io.py` as resource `sentiment_models` and typed `dg.ResourceParam[SentimentModels]`. Its constructor only stores `ollama_url` (env `OLLAMA_HOST`, default `http://localhost:11434`) and a `requests.Session`. `load(name)` imports torch/transformers on demand and returns a `Classifier`. When a library or service is missing it raises `ModelUnavailable` with the fix (`uv sync --group sentiment`, `ollama serve`, `ollama pull …`). The asset turns that into `dg.Failure(allow_retries=False)`. The torch models pick `cuda` when `torch.cuda.is_available()`, otherwise `cpu`, and log the device they use.
**Alternatives considered**: a `dg.ConfigurableResource` (the Phase 4 design found that a wrapper added nothing); a module-level `import torch` guarded by `try` (it slows `dg check defs` when torch is installed and hides partial installs).
**Rationale**: same pattern as `PoliteClient`. A guard test runs `import news_politica.definitions; defs()` in a subprocess and asserts that `"torch" not in sys.modules`.

### 3. The `sentiment` dependency group and the torch index

**Choice**: a `sentiment` group with `torch`, `transformers` and, if the spike keeps it, `pysentimiento`. torch comes from the PyTorch CPU index on every non-macOS platform:

```toml
[tool.uv.sources]
torch = [{ index = "pytorch-cpu", marker = "sys_platform != 'darwin'" }]

[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true
```

The group is not in uv's default groups (`dev` is the default), so `uv sync` does not install it.
**Alternatives considered**: PyPI torch, which on Linux pulls ~2.5 GB of CUDA wheels even on CPU-only machines; `cpu` and `cu12x` groups declared as `[tool.uv] conflicts`, which give two lock branches and a choice every teammate has to get right.
**Rationale**: the GPU-bound model, the LLM, runs inside Ollama, which ships its own CUDA runtime. Only robertuito (0.1B, about 3–8 min on CPU for 9.3k texts) and mDeBERTa (used only when there is no GPU) run in torch. So CUDA torch would buy nothing, and one CPU lock serves both machines.

**Spike rule (first task)**: keep pysentimiento only if (a) `uv lock` resolves for the full `>=3.11,<3.15` range, (b) `uv sync --group sentiment` on the project's Python 3.12 imports it with pandas 3 and the locked transformers, and (c) `create_analyzer(task="sentiment", lang="es")` predicts 5 sample texts. If (a) fails only because of spacy/thinc on 3.14, add `python_version < '3.14'` to pysentimiento and re-check. If (b) or (c) fails, drop pysentimiento and load `pysentimiento/robertuito-sentiment-analysis` with `AutoTokenizer` / `AutoModelForSequenceClassification` (softmax, label order from `config.id2label`, `max_length=128`). The spike also compares the two paths on about 20 texts and records the result in `docs/decision-sentimiento.md`, because pysentimiento preprocesses the text before the model. Only one path is implemented; there is no runtime fallback, so a machine never silently changes how it scores.

### 4. Models and their outputs

All three models return `(pos, neu, neg)` probabilities that sum to 1, so the long format is the same for each.

| `modelo` | Checkpoint / service | How the probabilities are produced |
|---|---|---|
| `robertuito` | `pysentimiento/robertuito-sentiment-analysis` | softmax over POS/NEU/NEG (`AnalyzerOutput.probas` or the logits) |
| `mdeberta-xnli` | `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` | `zero-shot-classification` pipeline, `multi_label=False`, candidate labels `positivo`/`neutro`/`negativo`, hypothesis `"El tono de esta noticia es {}."`, `batch_size=16`, truncation on |
| `qwen2.5-7b` | Ollama `qwen2.5:7b-instruct` (Q4_K_M, about 4.7 GB, fits the 8 GB RTX 4060) | see decision 5 |

`label` is the argmax (`pos`/`neu`/`neg`) and `score = prob_pos − prob_neg`. Scores from different models do not share a scale (one-hot LLM rows take values in {−1, 0, 1}), so every aggregate is grouped by `modelo` and never pooled across models.

### 5. Local LLM through Ollama's HTTP API

**Choice**: `OllamaClassifier` sends one `POST {ollama_url}/api/generate` per note with the existing `requests` dependency, so the LLM adds no Python package. Request: `stream: false`, `options: {temperature: 0, seed: 42, num_predict: 2}`, `logprobs: true`, `top_logprobs: 5`. Prompt (Spanish, constant in `classifiers.py`):

- system: "Clasificas el tono (valencia) de textos de noticias políticas argentinas. No evalúas la postura hacia el gobierno, solo si el texto es negativo, neutro o positivo."
- prompt: "Texto: «{texto}»\nResponde solo con un número: 1 = negativo, 2 = neutro, 3 = positivo."

The model answers with a digit rather than a word: digits are single tokens and differ from their first token, while `neutro` and `negativo` may share a first subword. Parsing: the first `1|2|3` in `response`. Probabilities: when the response has `logprobs`, take `exp(logprob)` of the tokens `1`, `2`, `3` among the first generated token's `top_logprobs` and renormalize. Otherwise, or when none of the three appear, use one-hot on the parsed digit. An unparseable answer gives NaN probabilities, `label = None` and a NaN score. Those rows are counted in the metadata and summary, and the aggregations drop them.
**Alternatives considered**: llama-cpp-python (a compiled CUDA build per machine, which is the opposite of the lean dependency goal); JSON-schema `format` output (the first token becomes `{`, which complicates reading logprobs); `/api/chat` (it works as well; `generate` is enough for one turn).
**Rationale**: no new dependency, deterministic (greedy plus a fixed seed), and three probabilities when Ollama gives logprobs. Whether the installed Ollama version returns `logprobs` is checked in the spike. The one-hot fallback keeps the contract either way.

**Availability and hardware rule**: `load("qwen2.5-7b")` checks `GET /api/tags`. If the connection is refused, it raises `ModelUnavailable` ("Ollama is not reachable at …; run `ollama serve`"). If the model is missing, it raises `ModelUnavailable` ("run `ollama pull qwen2.5:7b-instruct`"). `SentimentModels.alternative()` returns `qwen2.5-7b` only when Ollama is reachable, the model is pulled, and, after one warm-up request, `GET /api/ps` reports the model with `size_vram > 0` (that is, Ollama placed it on an NVIDIA GPU). Otherwise it returns `mdeberta-xnli` and logs a warning with the reason. Explicit model names never fall back; only `alternative()` chooses. No subprocess (`nvidia-smi`) is used. `torch.cuda` is not used either, because the CPU torch build always reports False.

### 6. `sentimiento_noticias`: one asset, configurable models, long format

**Choice**: `ScoringConfig(dg.Config)` with `modelos: list[str] = [MODELO_FINAL]`. `MODELO_FINAL` is a constant in `defs/sentiment.py`, `"robertuito"` until the decision doc names the chosen model. The asset scores every note of `noticias_politica`, including live ones, once per model and concatenates the results. Columns: `id, modelo, fuente_texto, prob_pos, prob_neu, prob_neg, label, score`. Note attributes (`medio`, `fecha_publicacion`, `es_en_vivo`) stay in `noticias_politica` and are joined on `id` downstream. No pool, no retry policy. The Ollama call goes to localhost and is not outlet traffic.
**Alternatives considered**: one asset per model (more graph nodes and a downstream union for a comparison that only happens once); a static partition per model (the downstream would read a dict of partitions, and re-running one model leaves stale partitions of others); evaluating through the asset (scoring 9.3k notes with mDeBERTa on CPU, about 30–90 min, just to read 300 rows).
**Rationale**: long format stays intact, the default run is a single model, and adding a second model is a launch-time config change. Model comparison happens in the notebook on the 300 labeled notes only (decision 8).

**Logging**: `BATCH_SIZE = 32`. Progress is logged every `LOG_EVERY` (10) batches, about every 320 notes and about 29 lines per model: start `"robertuito: scoring 9261 notes on cpu"`, progress `"robertuito: 320/9261 notes scored"`, summary `"robertuito: 9261 notes scored (4100 neg, 3900 neu, 1261 pos, 0 unparsed)"`. Metadata: `rows`, `rows_per_modelo`, `labels` (JSON per model), `unparsed`. `score_notes(..., log=)` logs the progress itself, the same pattern as `sampled_catalog(log=)`.

### 7. Analysis text

`analysis_text(titulo, bajada, cuerpo) -> (texto, fuente_texto)`: `titulo + ". " + bajada` (`fuente_texto="bajada"`). When `bajada` is empty, the title plus the first non-empty `\n\n` paragraph of `cuerpo` (`"cuerpo"`). When both are empty, the title alone (`"titulo"`). A trailing period on the title is not doubled. `fuente_texto` is what lets the evaluation and the series separate notes with and without a bajada (the MisionesOnline bajada-drift risk).

### 8. Labeling sample, export, merge and evaluation

- **Sample**: eligible notes are those with `es_en_vivo` false and a non-empty `titulo`. Per outlet, order by `sha1(SAMPLE_SALT + id)` with `SAMPLE_SALT = "etiquetado-2026-10"` and take the first 100. This is the salted-hash pattern of `SAMPLE_PER_MONTH`: stable across row order and pandas versions, with the salt as the recorded seed. Annotator: alternate `a`/`b` down the hash order within each outlet, so each annotator gets 50 per outlet, 150 in total, with no overlap.
- **Export**: `export_sheets(sample, out_dir)` writes `data/etiquetado/anotador_{a,b}.csv` (gitignored: it holds scraped text), `utf-8-sig` for spreadsheets. Columns `id, texto, etiqueta` (empty), in hash order. Outlet and model output are not shown.
- **Merge**: `read_labels(paths, sample)` checks that every `etiqueta` is in `{pos, neu, neg, descartar}`, that ids belong to the sample and that there are no duplicates or blanks, then writes the committed file `anotaciones/etiquetas.csv` (`id, anotador, etiqueta`). No text is committed.
- **Evaluation**: in the notebook, each candidate model scores the 300 sample texts directly (`score_notes` on the sample). Then `evaluate(labels, scores)`, excluding `descartar`, returns macro F1 and the confusion matrix per `modelo`, per `modelo × medio`, and per `modelo × fuente_texto`. Implemented in pandas, without scikit-learn.

**Alternatives considered**: `DataFrame.sample(random_state=…)` (it depends on row order); committing the texts (the proposal commits ids and labels only); a top-level `labels/` directory plus a separate milestones directory.
**Rationale**: `anotaciones/` is the single versioned folder for human-authored inputs (labels and milestones), outside the gitignored `data/`.

### 9. Weekly grain, intervals and the minimum-n rule

- **Week**: ISO week in ART. `fecha_publicacion` is converted to ART, and `semana` is the Monday date (00:00 ART) of that week. A note at Sunday 23:30 ART belongs to that Sunday's week even though it is Monday in UTC. The first week (2023-12-04, only Sunday 10th in range) and the last (2026-09-28, Monday to Wednesday) are partial and keep `n` as is.
- **`evolucion_tono` columns**, per `(modelo, medio, semana)`: `n`, `score_medio`, `ic_inf`, `ic_sup`, `prop_pos`, `prop_neu`, `prop_neg`, `prop_bajada`. Live notes and NaN scores are excluded. `prop_bajada` is the bajada coverage that the proposal requires next to the series.
- **CI**: 95 % Student t on the mean, `mean ± t(0.975, n−1)·s/√n`, computed for `n ≥ 2` (NaN below that). `scipy` becomes a main dependency for `scipy.stats.t`. Every point gets an interval, as the proposal requires; the normal approximation would be about 20 % too narrow at the Arc outlets' n≈7.
- **Minimum n** (`N_MIN = 10`) applies to the before/after windows, not to weekly points. Weekly Arc points (n≈7) are drawn with their wide intervals, and the notebook overlays the 4-week rolling mean.

**Alternatives considered**: a hard-coded t table (unclear to review); bootstrap (randomness and runtime); a normal approximation (too narrow at n≈7).

### 10. Milestones and before/after comparison

- **File** `anotaciones/hitos.csv`: `hito, fecha, alcance, fuente`. `fecha` is the first ART day on which coverage of the event can appear (for example the announcement day), `alcance` is `nacional|misiones`, and `fuente` is a URL. Initial rows: DNU 70/2023, the Senate approval of Ley Bases (June 2024), the 2025-10-26 legislative elections, and a Misiones placeholder. The team verifies dates against `fuente` before commit. The Misiones placeholder row has an empty `fecha` until the team names the event, and `compare_milestones` leaves it out of the table.
- **Windows**: before = `[fecha − 14 d, fecha)`, after = `[fecha, fecha + 14 d)`, at 00:00 ART and clipped to the dataset period `[2023-12-10, 2026-10-01)`. `dias_antes` / `dias_despues` report the clipped length, and `truncada` is true when either side is shorter than 14 days (DNU: before ≈ 11 days).
- **Output** of `compare_milestones(scores, notes, milestones)`, per `(modelo, hito, medio)`, for every outlet regardless of `alcance` (the notebook filters): `n_antes, n_despues, score_antes, score_despues, diferencia, ic_inf, ic_sup` (Welch t interval of the difference), `prop_neg_antes, prop_neg_despues, insuficiente` (either side below `N_MIN`), and `truncada`. Live notes are excluded. The comparison is descriptive, with no test statistic beyond the interval.

### 11. Where the notebook and docs fit

`notebooks/05_sentimiento.ipynb` is created in work unit 1 with the evaluation section and extended in work unit 2 with the weekly charts (4-week rolling mean, milestones marked) and the before/after table. `docs/guia-etiquetado.md` and `docs/decision-sentimiento.md` are in Spanish (team docs).

## Data Flow

```
noticias_politica ──▶ sentimiento_noticias (config modelos) ──▶ evolucion_tono
        │                     ▲ sentiment_models resource            ▲
        │                     │ (lazy torch / Ollama HTTP)           │
        └─────────── join on id ─────────────────────────────────────┘

notebook 05:  noticias_politica ─▶ labeling_sample ─▶ data/etiquetado/*.csv ─(humans)─▶ read_labels ─▶ anotaciones/etiquetas.csv
              sample texts ─▶ score_notes(robertuito, alternative()) ─▶ evaluate ─▶ docs/decision-sentimiento.md ─▶ MODELO_FINAL
              sentimiento_noticias + noticias_politica + anotaciones/hitos.csv ─▶ compare_milestones ─▶ table
              evolucion_tono ─▶ weekly charts
```

## File Changes

| File | Action | Description |
|---|---|---|
| `pyproject.toml`, `uv.lock` | Modify | `sentiment` group, PyTorch CPU index and source, `scipy` in the main dependencies |
| `src/news_politica/sentiment/__init__.py` | Create | Package docstring |
| `src/news_politica/sentiment/text.py` | Create | `analysis_text` |
| `src/news_politica/sentiment/classifiers.py` | Create | `Classifier`, three wrappers, `SentimentModels`, `ModelUnavailable`, prompt constants |
| `src/news_politica/sentiment/scoring.py` | Create | `score_notes`, `BATCH_SIZE` |
| `src/news_politica/sentiment/labeling.py` | Create | Sample, export, merge |
| `src/news_politica/sentiment/evaluation.py` | Create | Macro F1, confusion matrix |
| `src/news_politica/sentiment/tone.py` | Create | `weekly_tone`, `compare_milestones`, `N_MIN`, `WINDOW_DAYS` |
| `src/news_politica/defs/sentiment.py` | Create | `sentimiento_noticias`, `evolucion_tono`, `ScoringConfig`, `MODELO_FINAL` |
| `src/news_politica/defs/io.py` | Modify | Register the `sentiment_models` resource; docstring |
| `anotaciones/etiquetas.csv` | Create | 300 labels (ids and labels only), after labeling |
| `anotaciones/hitos.csv` | Create | Milestones with sources |
| `tests/sentiment/test_*.py` | Create | Pure-logic tests (text, Ollama parsing, labeling, evaluation, tone) |
| `tests/defs/test_sentiment_assets.py` | Create | Asset tests with a fake loader, logs, torch-free import guard |
| `tests/defs/conftest.py`, `tests/defs/test_assets.py` | Modify | Move `info_logs` to the conftest so both asset test files share it |
| `notebooks/05_sentimiento.ipynb` | Create | Labeling export and merge, evaluation, charts, before/after table |
| `docs/guia-etiquetado.md`, `docs/decision-sentimiento.md` | Create | Labeling guide; model decision with numbers (Spanish) |
| `README.md`, `docs/def.md`, `odd/tasks/news-politica.md` | Modify | `uv sync --group sentiment`, Ollama/GPU note, Phase 5 status |

## Interfaces / Contracts

```python
Probs = tuple[float, float, float]          # (pos, neu, neg); sums to 1, or all NaN when unparsed

class Classifier(Protocol):
    name: str                               # the `modelo` value
    device: str                             # "cpu", "cuda" or "ollama"
    def predict(self, texts: list[str]) -> list[Probs]: ...

class ModelUnavailable(RuntimeError): ...

class SentimentModels:
    def __init__(self, ollama_url: str = OLLAMA_URL, session=None): ...
    def load(self, name: str) -> Classifier: ...        # "robertuito" | "mdeberta-xnli" | "qwen2.5-7b"
    def alternative(self) -> str: ...                   # "qwen2.5-7b" or "mdeberta-xnli" (decision 5)

def analysis_text(titulo: str, bajada: str, cuerpo: str) -> tuple[str, str]: ...
def score_notes(notes: pd.DataFrame, classifier: Classifier, batch_size=BATCH_SIZE, log=None) -> pd.DataFrame: ...
def labeling_sample(notes: pd.DataFrame, per_medio=100, salt=SAMPLE_SALT) -> pd.DataFrame: ...  # id, medio, texto, fuente_texto, anotador
def export_sheets(sample: pd.DataFrame, out_dir: Path) -> list[Path]: ...
def read_labels(paths: list[Path], sample: pd.DataFrame) -> pd.DataFrame: ...                  # id, anotador, etiqueta
def evaluate(labels, scores, by=("modelo",)) -> tuple[pd.DataFrame, pd.DataFrame]: ...         # (macro F1 + per-class F1, confusion)
def weekly_tone(scores: pd.DataFrame, notes: pd.DataFrame) -> pd.DataFrame: ...
def compare_milestones(scores, notes, milestones, days=WINDOW_DAYS, n_min=N_MIN) -> pd.DataFrame: ...
```

## Testing Strategy

| Layer | What to test | Approach |
|---|---|---|
| Unit | `analysis_text` with bajada, empty bajada (first paragraph), both empty, no doubled period | Plain asserts |
| Unit | Ollama mapping with logprobs, without logprobs (one-hot), unparseable answer (NaN); unreachable server and missing model raise `ModelUnavailable`; `alternative()` with `size_vram` 0 and > 0 | `OllamaClassifier` / `SentimentModels` built on a fake session with canned JSON, the same idea as `FakeSession` |
| Unit | Sample: live notes and empty titles excluded, per-outlet size, the same ids after shuffling the rows, a/b split with no overlap; `read_labels` rejects unknown labels, foreign ids and duplicates | Small synthetic frames, `per_medio=4` |
| Unit | Macro F1 and confusion on a hand-computed case; `descartar` excluded | Plain asserts |
| Unit | Week assignment across the Sunday-night ART/UTC boundary; live notes excluded; t interval against a known value; NaN interval at n=1 | Synthetic frames |
| Unit | Before/after: clipped DNU window (`truncada`, `dias_antes=11`), the milestone day counted as "after", `insuficiente` below `N_MIN` | Synthetic frames |
| Asset | `sentimiento_noticias` gives one row per `(id, modelo)` for two configured models, `score = pos − neg`, metadata; `ModelUnavailable` becomes a non-retryable failure | `dg.materialize` with `noticias_politica.parquet` stored in `tmp_path` and a `FakeModels` resource whose classifier maps keywords to fixed probabilities |
| Asset | Logs: start, progress at 10 and 20 batches for 25 batches, summary | `DagsterInstance.ephemeral()` with the shared `info_logs` |
| Asset | `evolucion_tono` columns and live exclusion | `dg.materialize` from the stored Parquet files |
| Guard | Loading the definitions does not import torch | Subprocess `python -c` that checks `sys.modules` |

None of these tests needs the network, torch or Ollama. Real-model smoke runs (the spike, and the notebook evaluation) are manual and recorded in the decision doc.

## Threat Matrix

N/A: no routing, shell commands, subprocess in production code, VCS/PR automation, or executable-file classification. The only process boundary is an HTTP call to a local Ollama on the configured URL, with failure behavior defined in decision 5. The torch-import guard uses a subprocess only inside a test.

## Migration / Rollout

No migration required. The change only adds code, docs, a dependency group and Parquet outputs. Order: spike and lock, then the sample and guide (they unblock labeling), then the classifiers and `sentimiento_noticias` with robertuito, then evaluation once the labels are in, then `MODELO_FINAL` and the final materialization. Work unit 2 can be built on the robertuito output in parallel with labeling.

**Size forecast (authored lines, advisory budget 400 per review)**:

| Work unit | Code | Tests | Docs/notebook/other | Total |
|---|---|---|---|---|
| WU1: dependencies, text, classifiers, scoring, labeling, evaluation, `sentimiento_noticias` | ~380 | ~220 | ~150 (guide, decision, README, notebook evaluation section) | ~750 |
| WU2: `tone.py`, `evolucion_tono`, milestones | ~140 | ~130 | ~150 (notebook charts and table, def/odd updates) | ~420 |

`uv.lock` and notebook outputs are generated and not counted. With the `single-pr` strategy the PR is about 1,150 authored lines, roughly three times the advisory budget, so splitting WU1 into its own commits (dependencies/spike, pure logic, asset) helps review.

## Open Questions

- [ ] Does the installed Ollama version return `logprobs` / `top_logprobs` on `/api/generate`, and does `/api/ps` report `size_vram`? (Checked in the spike; the one-hot fallback keeps the contract either way.)
- [ ] Is pysentimiento's preprocessing material for news text? (The spike's 20-text comparison decides whether the transformers path is acceptable.)
- [ ] Exact milestone dates and the Misiones event (team decision, verified against sources before commit).
- [ ] Annotator identities for `a` and `b` (team decision; only the letters are committed).
