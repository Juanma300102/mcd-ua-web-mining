# Tasks: Sentiment analysis of political news (Phase 5)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1,150 authored (WU1 ~750, WU2 ~420); `uv.lock` and notebook outputs not counted |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | Single PR with 8 commits (below); a split into PR 1 (WU1) and PR 2 (WU2) is the natural alternative |
| Delivery strategy | single-pr |
| Chain strategy | size-exception |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: size-exception
400-line budget risk: High

The strategy is `single-pr`, so the orchestrator must obtain `size:exception` (or switch to a split) from the humans before apply. If they choose to split, the cut is between WU1 and WU2 (`feature-branch-chain`: PR 1 base = tracker branch, PR 2 base = PR 1 branch).

### Per-work-unit estimate

| Unit | Code | Tests | Docs / notebook / other | Total |
|------|------|-------|-------------------------|-------|
| WU1 | ~380 | ~220 | ~150 | ~750 |
| WU2 | ~140 | ~130 | ~150 | ~420 |
| Total | ~520 | ~350 | ~300 | ~1,170 |

### Proposed commit boundaries (each coherent, tests and docs with the code)

| Commit | Contents | Tasks | Est. lines |
|--------|----------|-------|-----------|
| C1 | `chore(sentiment)`: spike record, `sentiment` group, CPU torch index, scipy | 1.x, 2.x | ~90 (+ lock) |
| C2 | `feat(sentiment)`: analysis text, labeling sample/export/merge, tests, labeling guide | 3.x | ~230 |
| C3 | `feat(sentiment)`: classifiers, `SentimentModels`, scoring, tests | 4.x | ~300 |
| C4 | `feat(defs)`: `sentimiento_noticias`, resource registration, shared `info_logs`, asset tests, torch-free guard | 5.x | ~190 |
| C5 | `feat(sentiment)`: evaluation, notebook 05 (labeling and evaluation sections), tests | 6.x | ~150 |
| C6 | `docs(sentiment)`: labels file, decision doc, `MODELO_FINAL` | 7.x | ~60 |
| C7 | `feat(sentiment)`: tone, milestone comparison, `hitos.csv`, `evolucion_tono`, tests | 8.x | ~270 |
| C8 | `docs(sentiment)`: notebook charts and table, README, `docs/def.md`, ODD file | 9.x | ~150 |

Only C2 and C5 to C8 touch human-gated data; C3, C4 and C7 can be built while the two members label.

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Scoring and model choice: `sentimiento_noticias`, labeling, evaluation, decision doc | PR 1 (or C1 to C6 of the single PR) | `uv run pytest tests/sentiment tests/defs/test_sentiment_assets.py` | Materialize `sentimiento_noticias` with robertuito on the dev machine (task 7.4); notebook 05 evaluation section | Revert C1 to C6: removes the `sentiment` package, its assets, group and docs; `noticias_politica` untouched |
| 2 | Tone over time and milestones: `evolucion_tono`, `hitos.csv`, comparison, charts | PR 2 (or C7 to C8) | `uv run pytest tests/sentiment/test_tone.py tests/defs/test_sentiment_assets.py` | Materialize `evolucion_tono` from the stored sentiment Parquet (task 9.2); notebook 05 charts | Revert C7 to C8: removes `tone.py`, `evolucion_tono`, milestones; WU1 keeps working |

Conventions for every code task: tests go in the same task or commit (TDD is off, `strict_tdd: false`). Checks per task: `uv run pytest` and `uv run dg check defs`, both without the `sentiment` group installed (except the spike and the manual smoke runs). Tasks marked **[HUMAN]** cannot be done by the apply agent. Tasks marked **[NETWORK]** download models or packages (Hugging Face, PyTorch index, Ollama registry); none of them request news sites.

## 1. Dependency spike (first, blocks everything that guesses)

- [x] 1.1 **[NETWORK]** Create `docs/decision-sentimiento.md` (Spanish) with a "Spike" section. Run `uv lock` with a draft `sentiment` group (`torch`, `transformers`, `pysentimiento`) in a scratch copy or branch and record: does it resolve for `>=3.11,<3.15`? If it fails only because of spacy/thinc on 3.14, retry with `python_version < '3.14'` on pysentimiento and record the result. Check: the section states the resolution outcome.
- [x] 1.2 **[NETWORK]** With the project's Python 3.12, run `uv sync --group sentiment` and record: does `import pysentimiento` work with pandas 3 and the locked transformers, and does `create_analyzer(task="sentiment", lang="es")` predict 5 sample texts? Apply the spike rule from design decision 3 and write the verdict (keep pysentimiento or use `AutoTokenizer` / `AutoModelForSequenceClassification` with softmax, label order from `config.id2label`, `max_length=128`) in `docs/decision-sentimiento.md`. Check: verdict recorded.
- [x] 1.3 **[NETWORK]** Compare pysentimiento and the plain transformers path on about 20 texts (title plus bajada from `noticias_politica`) and record the agreement in `docs/decision-sentimiento.md`. Answers the open question on preprocessing. Check: a small table of 20 rows or a summary count is in the doc.
- [ ] 1.4 **[HUMAN]** **[NETWORK]** On the dev machine with the GPU: `ollama pull qwen2.5:7b-instruct`, call `POST /api/generate` with `logprobs: true, top_logprobs: 5, num_predict: 2` and check the response carries logprobs; call `GET /api/ps` after a request and check `size_vram > 0`. Record the Ollama version and both results in `docs/decision-sentimiento.md`. If logprobs are missing, record that the one-hot fallback applies. Check: both answers are in the doc.

## 2. Dependencies and lock (C1)

- [x] 2.1 `pyproject.toml`: add the `sentiment` dependency group per the spike verdict (not in uv's default groups), the `[tool.uv.sources]` torch entry with marker `sys_platform != 'darwin'` and the `[[tool.uv.index]]` `pytorch-cpu` explicit index; add `scipy` to the main dependencies. **[NETWORK]** Run `uv lock`. Check: `uv sync` (default groups) does not install torch; `uv run pytest` and `uv run dg check defs` pass.
- [x] 2.2 `.gitignore`: add `data/etiquetado/` if not already covered by `data/` (already covered by `data/`; verified with `git check-ignore -v`, no change). Check: `git check-ignore data/etiquetado/anotador_a.csv` matches.

## 3. Analysis text and labeling pipeline (C2; unblocks the human critical path)

- [x] 3.1 Create `src/news_politica/sentiment/__init__.py` (docstring) and `src/news_politica/sentiment/text.py` with `analysis_text(titulo, bajada, cuerpo) -> (texto, fuente_texto)` per design decision 7 (no doubled period, first non-empty `\n\n` paragraph, `fuente_texto` in `bajada|cuerpo|titulo`).
- [x] 3.2 Create `tests/sentiment/test_text.py` covering the three spec scenarios of "The analysis text is the title plus the bajada" plus the doubled-period case. Check: `uv run pytest tests/sentiment/test_text.py`.
- [x] 3.3 Create `src/news_politica/sentiment/labeling.py`: `SAMPLE_SALT = "etiquetado-2026-10"`, `labeling_sample` (eligible: not live, non-empty title; order per outlet by `sha1(salt + id)`; take 100; alternate `a`/`b`; columns `id, medio, texto, fuente_texto, anotador`), `export_sheets` (writes `data/etiquetado/anotador_{a,b}.csv`, `utf-8-sig`, columns `id, texto, etiqueta`, hash order, no outlet or model output), `read_labels` (validates labels in `{pos, neu, neg, descartar}`, ids in the sample, no duplicates or blanks; returns `id, anotador, etiqueta`).
- [x] 3.4 Create `tests/sentiment/test_labeling.py` with `per_medio=4` synthetic frames: live notes and empty titles excluded; size per outlet; same ids after shuffling rows; a/b split disjoint and balanced per outlet; export columns and no outlet column; `read_labels` rejects unknown labels, foreign ids, duplicates and blanks. Spec scenarios: balanced draw, reproducible draw, disjoint split, committed labels carry no text. Check: `uv run pytest tests/sentiment/test_labeling.py`.
- [x] 3.5 Create `docs/guia-etiquetado.md` (Spanish): definitions of positivo, neutro, negativo and descartar; the label is the valence of the text, not stance toward the government; examples; how to fill `etiqueta` in the CSV; annotators do not see model output.
- [x] 3.6 Create `notebooks/05_sentimiento.ipynb` with the "Etiquetado" section only: load `noticias_politica`, build the sample, export the two sheets, and a cell for `read_labels` that writes `anotaciones/etiquetas.csv`. Check: the export cell runs against the real dataset and produces two files of 150 rows each with no shared id.
- [ ] 3.7 **[HUMAN]** After C2 is available, generate the sheets and hand `data/etiquetado/anotador_a.csv` and `anotador_b.csv` to the two members. Decide which member is `a` and which is `b` (only the letters are committed).
- [ ] 3.8 **[HUMAN]** Each member labels their 150 notes following `docs/guia-etiquetado.md` (about 1.7 h each). This is the critical path between the two work units; continue with sections 4, 5 and 8 meanwhile.
- [x] 3.9 Review follow-ups on C2 (commit `fix(sentiment)`): `export_sheets` refuses to overwrite existing sheets unless `overwrite=True` and the notebook export/merge cells are independent; `analysis_text` keeps terminal punctuation and ellipses; `labeling_sample` rejects duplicate ids and coerces `es_en_vivo` safely; `read_labels` compares ids as strings, checks each sheet's ids against its annotator, ignores blank rows and names the sheet on missing columns. Tests added in `tests/sentiment/test_text.py` and `test_labeling.py`.

## 4. Classifiers and scoring (C3)

- [x] 4.1 Create `src/news_politica/sentiment/classifiers.py`: `Probs`, `Classifier` protocol (`name`, `device`, `predict`), `ModelUnavailable`, the Spanish prompt constants, and `OllamaClassifier` (`POST /api/generate` with `stream: false`, `options {temperature 0, seed 42, num_predict 2}`, `logprobs`, `top_logprobs: 5`; first `1|2|3` in `response`; probabilities from `exp(logprob)` of tokens `1/2/3` in the first token's `top_logprobs`, renormalized; one-hot fallback; NaN when unparseable). No torch import.
- [x] 4.2 In `classifiers.py`, add the torch wrappers `RobertuitoClassifier` (path chosen in task 1.2; softmax over POS/NEU/NEG; device `cuda` if `torch.cuda.is_available()` else `cpu`, logged) and `MdebertaClassifier` (`zero-shot-classification`, `multi_label=False`, labels `positivo/neutro/negativo`, hypothesis `"El tono de esta noticia es {}."`, `batch_size=16`, truncation). All torch, transformers and pysentimiento imports stay inside methods.
- [x] 4.3 In `classifiers.py`, add `SentimentModels` (`__init__(ollama_url=OLLAMA_URL, session=None)`, env `OLLAMA_HOST`, default `http://localhost:11434`; `load(name)`; `alternative()` per the hardware rule: Ollama reachable, model pulled, one warm-up request, `GET /api/ps` `size_vram > 0`, else `mdeberta-xnli` with a logged warning). `load` raises `ModelUnavailable` with the fix text (`uv sync --group sentiment`, `ollama serve`, `ollama pull qwen2.5:7b-instruct`). Explicit names never fall back. No subprocess, no `nvidia-smi`.
- [x] 4.4 Create `tests/sentiment/test_classifiers.py` using a fake session with canned JSON (same idea as the existing `FakeSession`): mapping with logprobs, without logprobs (one-hot), unparseable answer (NaN probabilities, `label` None path); unreachable server and missing model raise `ModelUnavailable`; `alternative()` with `size_vram` 0 and > 0 and with Ollama down. Spec scenarios: GPU detected, no GPU. Check: `uv run pytest tests/sentiment/test_classifiers.py` offline.
- [x] 4.5 Create `src/news_politica/sentiment/scoring.py`: `BATCH_SIZE = 32`, `LOG_EVERY = 10`, `score_notes(notes, classifier, batch_size, log)` building the long frame (`id, modelo, fuente_texto, prob_pos, prob_neu, prob_neg, label, score`) through `analysis_text`, with progress lines every `LOG_EVERY` batches and the summary line (neg/neu/pos/unparsed counts).
- [x] 4.6 Create `tests/sentiment/test_scoring.py` with a keyword fake classifier: one row per note, `score = pos - neg` (0.7/0.2/0.1 gives 0.6, label `pos`, probabilities sum to 1), NaN rows keep `label` None and are counted, progress logged at batches 10 and 20 for 25 batches, summary line. Check: `uv run pytest tests/sentiment/test_scoring.py`.
- [x] 4.7 Review follow-ups on C3 (commit `fix(sentiment)`): `OllamaClassifier.parse` reads the digit weights from the `top_logprobs` of the generated token that carries the answer digit (not always the first token; one-hot when no token carries it); non-JSON bodies, unexpected shapes and ill-typed fields (e.g. `size_vram`) become `ModelUnavailable` at `_get` / `_predict_one` / ps parsing, so `alternative()` falls back to `mdeberta-xnli` for any failure while explicit names still fail. Tests in `tests/sentiment/test_classifiers.py`.

## 5. Asset `sentimiento_noticias` (C4)

- [x] 5.1 Create `src/news_politica/defs/sentiment.py` with `ScoringConfig(dg.Config)` (`modelos: list[str] = [MODELO_FINAL]`), `MODELO_FINAL = "robertuito"`, and the `sentimiento_noticias` asset: reads `noticias_politica`, scores each configured model through `score_notes` with the `sentiment_models` resource (`dg.ResourceParam[SentimentModels]`), concatenates, INFO start line, summary line with model and count, metadata `rows`, `rows_per_modelo`, `labels` (JSON per model), `unparsed`; `ModelUnavailable` becomes `dg.Failure(allow_retries=False)`. No pool, no retry policy.
- [x] 5.2 `src/news_politica/defs/io.py`: register the `sentiment_models` resource; update the module docstring. Check: `uv run dg check defs` passes without the `sentiment` group.
- [x] 5.3 Move `info_logs` from `tests/defs/test_assets.py` into `tests/defs/conftest.py` and import it from both asset test files. Check: `uv run pytest tests/defs/test_assets.py` still passes.
- [x] 5.4 Create `tests/defs/test_sentiment_assets.py`: with `noticias_politica.parquet` in `tmp_path` and a `FakeModels` resource, check one row per `(id, modelo)` for two configured models, `score = pos - neg`, metadata, `noticias_politica` byte-identical after the run, `ModelUnavailable` gives a non-retryable failure, and with `DagsterInstance.ephemeral()` the INFO start, progress and summary lines for 25 batches. Spec scenarios: one row per note and model, probabilities label and score, source dataset untouched, scoring logs.
- [x] 5.5 In the same test file, add the torch-free guard: a subprocess `python -c` that imports `news_politica.definitions`, calls `defs()` and asserts `"torch" not in sys.modules`. Spec scenarios: torch not installed, no torch no network, definitions check. Check: `uv run pytest` and `uv run dg check defs` pass offline without the `sentiment` group.
- [x] 5.6 Review follow-ups on C3/C4 (commit `fix(sentiment)`): `ModelUnavailable` raised during `score_notes` becomes a non-retryable `dg.Failure` naming the model; a malformed `/api/generate` answer for one note yields NaN probabilities (only transport/server-level problems and a missing `response` text raise `ModelUnavailable`; programming errors propagate) and `_digit_weights` skips non-dict entries; non-finite `size_vram` is rejected; one `_json_object` guard replaces the duplicated body checks; `ScoringConfig.modelos` deduplicates preserving order; the unknown-model branch catches only the new `UnknownModel(ValueError)`; shared test helpers (`UPSTREAM`, `store`, `metadata`, `info_logs`) live in `tests/defs/conftest.py`.

## 6. Evaluation (C5)

- [x] 6.1 Create `src/news_politica/sentiment/evaluation.py`: `evaluate(labels, scores, by=("modelo",))` returning `(macro F1 + accuracy + per-class F1, confusion matrix)` in pandas without scikit-learn; excludes `descartar`; groupings `modelo`, `modelo x medio`, `modelo x fuente_texto`.
- [x] 6.2 Create `tests/sentiment/test_evaluation.py`: hand-computed macro F1 and confusion case, perfect agreement gives accuracy and macro F1 of 1.0, `descartar` excluded (290 of 300 style case), per-outlet and per-`fuente_texto` rows present. Spec scenarios: perfect agreement, discarded notes, per-outlet metrics. Check: `uv run pytest tests/sentiment/test_evaluation.py`.
- [ ] 6.3 Extend `notebooks/05_sentimiento.ipynb` with the "Evaluacion" section: read `anotaciones/etiquetas.csv`, score the 300 sample texts with robertuito and with `SentimentModels.alternative()` (`score_notes` on the sample), call `evaluate`, show the tables and confusion matrices. Check: the section runs end to end once labels exist. (Section written and validated structurally with nbformat plus cell compilation; it stays unchecked until it is run with real labels and models, which needs 7.1 and 7.2.)
- [x] 6.4 Review follow-ups on C5 (commit `fix(sentiment)`): one Ollama error policy (`_call_ollama`, shared by generation and the `/api/tags` and `/api/ps` probes): timeouts, connection errors, HTTP 429 and 5xx are retried up to 3 attempts with a doubling backoff (0.5 s, 1 s; `sleep` injected, tests never wait) and then raise `ModelUnavailable`; other 4xx, other request exceptions and non-JSON or non-dict bodies raise at once. `parse` and its helpers type-check every field (wrong-typed `response`, `logprobs`, `top_logprobs`, entries, `token`, `logprob` give one-hot or NaN, never an exception) and `_finite_number` rejects ints too large for a float, also for `size_vram`. `evaluate` rejects duplicate ids in labels and `(id, modelo)` in scores, missing grouping values and predictions outside the classes (unparsed stays `sin_respuesta`, so confusion totals equal `n`), uses `math.isnan` and `enumerate`. New `load_labels` validates the committed `anotaciones/etiquetas.csv` with the checks of `read_labels` and the notebook uses it; the notebook no longer hard-codes 9.261 or 300. Tests drop the `ALL = UPSTREAM` alias.

## 7. Labels, model decision and final materialization (C6)

- [ ] 7.1 **[HUMAN]** Collect both completed CSVs into `data/etiquetado/` and run the notebook merge cell so `read_labels` validates them and writes `anotaciones/etiquetas.csv` (columns `id, anotador, etiqueta`, no text). Check: 300 rows, only those columns.
- [ ] 7.2 **[HUMAN]** **[NETWORK]** On the dev machine, run the evaluation section of the notebook (robertuito and the alternative; downloads weights from Hugging Face on first use; Ollama must be running for `qwen2.5-7b`). Record the machine name and which alternative `alternative()` chose.
- [ ] 7.3 Complete `docs/decision-sentimiento.md` (Spanish): macro F1 and confusion per model, per outlet and with/without bajada, the chosen model and why, the machine used, the domain-shift and bajada-drift caveats. Update `MODELO_FINAL` in `src/news_politica/defs/sentiment.py` to the chosen model name. Check: `uv run pytest` and `uv run dg check defs` still pass.
- [ ] 7.4 **[HUMAN]** **[NETWORK]** Materialize `sentimiento_noticias` with the chosen model on the dev machine (`uv sync --group sentiment`, Ollama up if the LLM won). Record duration, rows per `modelo`, `labels` and `unparsed` in the ODD progress notes (task 9.5). Check: one row per note for the chosen `modelo`, 9,261 rows.

## 8. Tone and milestones (C7; can start before labels exist, built on the baseline)

- [ ] 8.1 **[HUMAN]** Name the Misiones milestone event and verify every milestone date against its `fuente` URL: DNU 70/2023, Senate approval of Ley Bases (June 2024), 2025-10-26 legislative elections, the Misiones event. The date is the first ART day on which coverage can appear.
- [x] 8.2 Create `anotaciones/hitos.csv` (`hito, fecha, alcance, fuente`) with the four rows; the Misiones row keeps an empty `fecha` until 8.1 is done and `compare_milestones` leaves it out. (Done with an extra `verificado` column, all `false`, and empty `fuente` URLs: the DNU date 2023-12-20 comes from the spec and the elections date 2025-10-26 from the design; the Ley Bases day is not in the artifacts, so its `fecha` is empty too. Task 8.1 fills dates and sources and flips `verificado`. Note: the spec gives 2023-12-20 for the DNU, which yields `dias_antes` 10; the 11 days in this task and in the design correspond to 2023-12-21. 8.1 should settle which day is right.)
- [x] 8.3 Create `src/news_politica/sentiment/tone.py`: `N_MIN = 10`, `WINDOW_DAYS = 14`, `weekly_tone(scores, notes)` (ART ISO week, `semana` = Monday 00:00 ART; excludes live notes and NaN scores; columns `modelo, medio, semana, n, score_medio, ic_inf, ic_sup, prop_pos, prop_neu, prop_neg, prop_bajada`; Student t 95 % interval for `n >= 2` using `scipy.stats.t`, NaN below) and `compare_milestones(scores, notes, milestones, days, n_min)` (windows `[fecha - 14 d, fecha)` and `[fecha, fecha + 14 d)` at 00:00 ART clipped to `[2023-12-10, 2026-10-01)`; output per `(modelo, hito, medio)` with `n_antes, n_despues, score_antes, score_despues, diferencia, ic_inf, ic_sup` (Welch), `prop_neg_antes, prop_neg_despues, dias_antes, dias_despues, truncada, insuficiente`; a side below `N_MIN` reports no mean or share).
- [x] 8.4 Create `tests/sentiment/test_tone.py`: Sunday 23:30 ART note lands in that Sunday's week; live notes excluded (3 live + 2 regular gives `n` 2); scores 0.2, 0.4, 0.0, -0.2 give mean 0.1 and shares summing to 1; t interval against a known value; NaN interval at `n` 1; DNU window clipped (`truncada`, `dias_antes` 11); milestone day counted as "after"; `insuficiente` below `N_MIN` with no mean or share; Misiones row with empty date left out. Spec scenarios: weekly row, live notes excluded, single note, enough notes, too few notes, window before dataset start. Check: `uv run pytest tests/sentiment/test_tone.py`.
- [x] 8.5 In `src/news_politica/defs/sentiment.py`, add the unpartitioned `evolucion_tono` asset (reads `sentimiento_noticias` and `noticias_politica`, calls `weekly_tone`, INFO start line, summary line with the number of weekly rows, metadata `rows`).
- [x] 8.6 Extend `tests/defs/test_sentiment_assets.py`: `evolucion_tono` columns, live exclusion and the INFO start and summary lines, via `dg.materialize` from Parquet files in `tmp_path`. Spec scenarios: scoring logs (tone side), weekly row. Check: `uv run pytest` and `uv run dg check defs` pass offline.
- [x] 8.7 Review follow-ups on C5/C7 (commit `fix(sentiment)`): generation retries only connection errors (including connect timeouts) and HTTP 429/5xx; a read timeout raises `ModelUnavailable` at once (no 3 x 120 s wait); the `/api/tags` and `/api/ps` probes make one attempt with a 3 s timeout so `alternative()` falls back quickly; `generate` reuses its `where` string. `tone` rejects duplicated `(id, modelo)` score rows, normalizes milestone dates to 00:00 ART, takes `DATASET_START`/`DATASET_END` from `sources.arc` (`START`, new `CUTOFF`, also used by `defs/assets.py`) instead of duplicating them, and `tone_exclusions` counts dropped rows (`sin_nota`, `en_vivo`, `score_nan`, `sin_fecha`); `evolucion_tono` reports them in the INFO summary and the `excluidas` metadata. Notebook Evaluacion prerequisites split into two items. Tests in `test_classifiers.py`, `test_tone.py`, `test_sentiment_assets.py`.

## 9. Notebook, docs and close-out (C8)

- [ ] 9.1 Extend `notebooks/05_sentimiento.ipynb` with the "Evolucion" section (weekly series per outlet with the t interval and a 4-week rolling mean, milestones marked, bajada coverage `prop_bajada` shown next to the series) and the "Hitos" section (before/after table filtered by `alcance`, insufficient and truncated windows marked). Check: runs end to end on the materialized Parquet.
- [ ] 9.2 **[HUMAN]** Materialize `evolucion_tono` from the stored `sentimiento_noticias` and run the notebook sections of 9.1. Check: weekly points for the three outlets and a before/after row for every milestone with a date.
- [ ] 9.3 `README.md`: document `uv sync --group sentiment`, the CPU torch index, Ollama (`ollama serve`, `ollama pull qwen2.5:7b-instruct`, `OLLAMA_HOST`) and the GPU note, and how to materialize the two assets with `modelos` config.
- [ ] 9.4 `docs/def.md`: record the Phase 5 status and the analysis-text and model decisions (Spanish).
- [ ] 9.5 `odd/tasks/news-politica.md`: mark Phase 5 progress, with the materialization record from task 7.4 and the commit hashes of C1 to C8.
- [ ] 9.6 Final check: `uv run pytest` and `uv run dg check defs` pass in an environment without the `sentiment` group; confirm `data/etiquetado/` is untracked and `anotaciones/` holds only `etiquetas.csv` and `hitos.csv`.

## Dependency notes

- Sequential: 1 then 2 then 3; 4 then 5; 6 needs 4; 7 needs 3.8, 5 and 6; 8.5 needs 5.1; 9 needs 7 and 8.
- Parallel: 3.8 (human labeling) runs alongside 4, 5, 6.1 to 6.2 and 8; 8.1 (human milestone verification) can happen any time before 9.2.
- Bottlenecks: 3.8 (two people, about 1.7 h each) gates 7; 1.4 and 7.2 and 7.4 need the one GPU dev machine.
