## Why

`noticias_politica` is built (9,261 notes, 2023-12-10 to 2026-09-30), but the main question in `docs/def.md` is still open: how the tone of political news changed since December 2023, how it differs between Infobae, La Nación and MisionesOnline, and whether it shifts around political milestones. Phase 5 needs a sentiment score per note, a check of that score against a labeled sample, and a weekly series per outlet with a before/after table per milestone. This change covers Phase 5 (T5) as a lean proof of concept, based on `exploration.md`.

## What Changes

**Work unit 1: scoring and model choice**

- A `sentiment` dependency group in `pyproject.toml` / `uv.lock` (torch, transformers, pysentimiento), not installed by default. The first task is a spike: if pysentimiento does not resolve or run on Python 3.12 / pandas 3, use the same checkpoint (`pysentimiento/robertuito-sentiment-analysis`) through `transformers`.
- A pure `src/news_politica/sentiment/` package: the analysis text, scoring, labeling-sample builder, aggregation and before/after comparison, all testable without torch.
- Analysis text: `titulo + ". " + bajada`; when `bajada` is empty, title plus the first body paragraph.
- A model resource that imports torch lazily and uses CUDA when available, otherwise CPU. Two models:
  - baseline: robertuito (pysentimiento);
  - alternative: a local quantized 7–8B LLM (e.g. via Ollama) when an NVIDIA GPU is detected, otherwise mDeBERTa-v3 XNLI zero-shot.
- `sentimiento_noticias`: unpartitioned, reads `noticias_politica` and never changes it. Long format, one row per `(id, modelo)` with `prob_pos`, `prob_neu`, `prob_neg`, `label` and `score = prob_pos − prob_neg`. `modelo` records which model produced the row. No pool (no network).
- Labeling: a seeded sample of 300 notes (100 per outlet, no live notes, no empty titles), split 150/150 into two sheets with no overlap. The labels are produced by an Anthropic model (Claude Opus 5.5, 2026-10-29, recorded in `docs/decision-sentimiento.md`) instead of the team members, following the guide, with no human review. The labeler sees exactly the model input, blind to the model output. Labels are committed as ids and labels only. `docs/guia-etiquetado.md` (Spanish) defines positive, neutral, negative and discard; a label is the valence of the text, not stance toward the government.
- Model evaluation on the labels (macro F1 and confusion matrix per model and outlet). The final `sentimiento_noticias` is materialized with the chosen model.

**Work unit 2: tone over time and milestones**

- `evolucion_tono`: weekly per outlet (all three outlets), with `n`, mean score, its confidence interval and the share of each label. Live notes excluded.
- A versioned milestones file: DNU 70/2023, the Senate approval of Ley Bases (June 2024), the October 2025 legislative elections and one Misiones event (placeholder until the team names it). Dates are checked against sources before commit.
- Before/after comparison: 2-week windows on each side, mean score and negative share, `n` per side, and a window marked "insufficient" below a minimum `n`. The DNU "before" window is truncated by the 2023-12-10 dataset start and is reported as such.
- `notebooks/05_sentimiento.ipynb`: weekly charts with a 4-week rolling mean and the milestones marked, plus the before/after table.
- `docs/decision-sentimiento.md` (Spanish): which model was chosen and why, with the evaluation numbers.
- Both assets follow the `dagster-assets` conventions: INFO start and summary lines, offline tests with a fake classifier that do not need torch.

## Non-goals

- Scoring the body, per paragraph or whole.
- Re-scraping or widening the Arc sample, and refetching MisionesOnline (Cloudflare-challenged).
- Stance detection (tone toward the government).
- Inter-annotator agreement (out of scope in `docs/def.md`).
- Hosted or paid LLM APIs.
- Time-series or break-point models; the milestone comparison stays descriptive.
- Monthly grain or a different grain per outlet.

## Capabilities

### New Capabilities
- `sentiment-analysis`: the analysis text, the model resource and its CPU/GPU fallback, `sentimiento_noticias`, the labeling sample and guide, the model evaluation, `evolucion_tono`, the milestones file and the before/after comparison, with their logging and offline tests.

### Modified Capabilities
<!-- None: `dagster-assets` is followed as is; its logging and offline-test requirements are scoped to catalog, raw and dataset assets, so `sentiment-analysis` states its own. -->

## Impact

- New: `src/news_politica/sentiment/`, the sentiment assets and model resource under `src/news_politica/defs/`, tests under `tests/` (fake classifier, no torch), the milestones file and the labels file (outside the gitignored `data/`), `docs/guia-etiquetado.md`, `docs/decision-sentimiento.md`, `notebooks/05_sentimiento.ipynb`.
- Changed: `pyproject.toml` / `uv.lock` (`sentiment` group), `README.md` (`uv sync --group sentiment`, GPU note), `odd/tasks/news-politica.md` and `docs/def.md` (Phase 5 status).
- Not changed: `src/news_politica/sources/`, the existing assets and `noticias_politica`.
- Network: none from assets or tests. Downloading model weights (and the LLM, if used) is a one-off setup step outside the sandbox.
- Human time: none for labeling (done by Claude Opus 5.5); the labels are not human-reviewed.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| pysentimiento does not resolve or run on Python 3.12 / pandas 3 / transformers 5 | Med | Spike first; fall back to the same checkpoint via `transformers` |
| Domain shift: robertuito is trained on tweets, not news headlines | High | Measure it on the 300 labels; compare with the alternative and pick the better one |
| Weak weekly power for Infobae and La Nación (~7 notes/week, ~14 per 2-week window) | High | `n` and a confidence interval on every point, a 4-week rolling mean, the minimum-`n` rule, and the limitation stated in the report |
| The alternative model depends on hardware (LLM with GPU, mDeBERTa without), so runs differ between machines | Med | `modelo` on every row; the comparison and the final run are done on one named machine; the chosen model is recorded in the decision doc |
| The LLM gives a label, not three probabilities | Med | Design defines how the LLM output maps to `prob_*` (e.g. token probabilities or a one-hot fallback) |
| Labels are model-generated ("silver"), not human ground truth: metrics are agreement with Claude Opus 5.5, not with a human reading | High | State it in `docs/decision-sentimiento.md` and in the report; Claude is not an evaluated model, so there is no self-agreement |
| MisionesOnline's falling bajada coverage (≈98 % to ≈55 %) and `fuente_externa` share can look like a tone change | Med | Report bajada coverage per period next to the series; the evaluation reports metrics for notes with and without bajada |
| Dataset rerun changes ids and the labeling sample | Low | Treat the current `noticias_politica` as frozen for this phase; labels keyed by `id` with the sample seed recorded |

## Rollback Plan

The change only adds code, docs and a dependency group. Revert the PR; `noticias_politica` and the scraping assets are untouched, and the materialized sentiment Parquet files under `data/` can be deleted.

## Success Criteria

- `uv run pytest` and `uv run dg check defs` pass without the `sentiment` group installed.
- `sentimiento_noticias` holds one row per note for the chosen model, with `modelo` set.
- 300 labels (generated by Claude Opus 5.5) committed, with macro F1 per model and outlet in `docs/decision-sentimiento.md`.
- `evolucion_tono` gives weekly points per outlet with `n` and a confidence interval, and the notebook shows the charts and the before/after table for every milestone, with insufficient windows marked.
