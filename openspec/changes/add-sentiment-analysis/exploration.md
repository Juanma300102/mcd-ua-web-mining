# Exploration: add-sentiment-analysis (Phase 5)

## Current state

- **Dataset:** `data/noticias_politica.parquet` has 9,261 rows (Infobae 996, La Nación 1,020, MisionesOnline 7,245) and 13 columns. `data/` is gitignored (24.9 MB), so teammates share the Parquet out of band. Sentiment only reads `noticias_politica`, so the missing local `raw_misionesonline` partitions do not matter.
- **Volume:**
  - Infobae and La Nación: 30 notes per month (21–24 in some Infobae months), about 7 per week and 14 per 2-week window.
  - MisionesOnline: median 45 per week; about 170 per month until 2026-02 and about 320 from 2026-03.
- **Text fields:**
  - Bajada coverage: 100 % / 99.3 % / 69.4 % (Infobae / La Nación / MisionesOnline). At MisionesOnline it falls from about 98 % (to 2024-Q2) to about 55 % (from 2025).
  - Median lengths: title about 18 words, bajada 28–39 words.
  - Live notes: 14 at Infobae and 31 at La Nación, flagged by `es_en_vivo`.
  - `fuente_externa`: 12.7 % of MisionesOnline notes.
  - Bodies keep paragraph breaks (`\n\n`).
- **How assets plug in:**
  - Assets are plain `@dg.asset` functions that return DataFrames.
  - `ParquetIOManager` (`defs/io.py`) writes them under `data/`.
  - The `dagster-assets` spec requires an INFO start line and a summary, and offline tests with a fake resource.
  - A pool is only needed for assets that make network requests.
- **Dependencies:** no torch, transformers or `sentiment` group yet. `requires-python` is `>=3.11,<3.15`.

## Affected areas

- **Assets:** `sentimiento_noticias` and `evolucion_tono`, in `src/news_politica/defs/` (possibly a new `defs/sentiment.py`).
- **Pure logic:** a new `src/news_politica/sentiment/` package with the analysis text builder, scoring, aggregation, before/after comparison and labeling-sample builder, all testable offline.
- **Dependencies:** `pyproject.toml` / `uv.lock` get a `sentiment` group, probably installed from the CPU torch index.
- **Tests:** `tests/defs/` with a fake classifier.
- **Versioned files:** the milestones file, the labels (ids and labels only), `docs/guia-etiquetado.md` and `docs/decision-sentimiento.md`.
- **Other:** `notebooks/05_sentimiento.ipynb`, the README (`uv sync --group sentiment`), and a delta for `openspec/specs/dagster-assets/spec.md`.

## Evidence

### pysentimiento

- **Package:** PyPI 0.7.3 (2024-03-04), `requires_python >=3.8,<4`, classifiers up to 3.11.
- **Dependencies:** `torch>=2.0.0,!=2.0.1`, `transformers>=4.13.0` (no upper bound), `spacy`, `datasets`, `accelerate`, `emoji`.
- **Compatibility:** with Python 3.12, pandas 3 and transformers 5 it is unverified. A universal lock over `<3.15` may fail on spacy/thinc wheels.
- **Model:** `robertuito-sentiment-analysis`, about 0.1B parameters (about 500 MB), trained on TASS 2020 tweets with macro F1 0.705. Expect a domain shift to news headlines.
- **Input length:** title + bajada is about 90 tokens, so most notes fit. The default truncation length is unverified.
- **CPU time (estimate):** 3–8 minutes for 9.3k texts. A per-paragraph body variant would take about 15× longer.
- **Fallback:** if the lock fails, use `transformers` with the same checkpoint (same predictions, no spacy/datasets/accelerate).

### Alternative models

| Option | Pros | Cons | Effort |
|---|---|---|---|
| mDeBERTa-v3 XNLI zero-shot | 0.3B, MIT, Spanish XNLI 0.832, local, deterministic, not tied to tweets | About 3 hypotheses per note (about 28k pairs, ~30–90 min CPU, estimate); sensitive to label wording | Medium |
| distilbert multilingual sentiments (lxyuan) | 0.1B, Apache-2.0, fast, 3 classes | Distilled from pseudo-labels on reviews and tweets; no gold metric published | Low |
| Hosted LLM zero-shot | Best at news semantics | API key, cost, non-deterministic, sends text to a third party; needs authorization | Medium |
| Local LLM | No external dependency | Too slow on CPU | High |

### Granularity and statistical power

- **Arc outlets:**
  - Weekly: n≈7, standard error ≈0.15 (SD ≈0.4), so the weekly series is noise.
  - Monthly: n≈30, standard error ≈0.07.
  - 2-week milestone window: n≈14, standard error ≈0.11, so only shifts of about 0.3 or more are detectable.
- **MisionesOnline:** weekly (n≈45) and 2-week windows (n≈90) both work.
- **DNU 70/2023 window:** the date (about 2023-12-21) needs checking. The dataset starts on 2023-12-10, so the "before" window is truncated to about 11 days.
- **Widening the Arc sample:**
  - The current catalog lists about 50 URLs per month, so the sample can only grow to about 50 unless `SITEMAP_DAYS` widens.
  - 150 notes per month would take about 2.8 h of backfill per outlet and needs network authorization.
  - It must happen before the label sample is drawn, because the lowest-hash sample changes when the catalog changes.

### Labeling

- **Sample:** 100 per outlet, seeded, excluding live notes and empty titles. MisionesOnline includes notes without a bajada in proportion; those use title plus first paragraph.
- **Procedure:** annotators see exactly the text the model sees, blind to the model output.
- **Tooling:** a CSV export filled in a spreadsheet, plus a merge notebook.
- **Effort and precision:** about 1.7 h in total. With n=300 the macro F1 confidence interval is about ±5 points.

## Recommended approach (lean proof of concept)

- **Analysis text:** `titulo + ". " + bajada`, falling back to the first body paragraph when the bajada is empty.
- **`sentimiento_noticias`:** long format, one row per `(id, modelo)`, with `prob_pos`, `prob_neu`, `prob_neg`, the label and `score = prob_pos − prob_neg`.
  - The model resource imports torch lazily, so `dg check defs` and the tests run without the `sentiment` group.
  - Tests use a fake classifier.
- **Model comparison:** in a notebook, baseline vs. one alternative on the 300 labels.
- **`evolucion_tono`:** per outlet and period, with `n`, mean score, confidence interval and the share of each label.
  - Grain: monthly for all outlets, weekly for MisionesOnline.
  - Live notes are excluded by default.
- **Milestones:** a before/after table from a versioned milestones CSV, with a minimum `n` per side and confidence intervals.
- **Charts:** in a notebook.

Alternatives: widen the Arc sample first (only if the team wants milestone claims for the national outlets), or the full version (body per paragraph plus an LLM on every note), which costs about 15× the compute with little gain.

## Open product decisions

1. **Unit of analysis.** Recommended: title + bajada, with the body per paragraph as a Non-goal.
2. **Alternative model.** Recommended: mDeBERTa zero-shot, with distilbert as a cheap fallback. An LLM only as a reference on the 300 labels, and only if authorized.
3. **Grain / widening.** Recommended: monthly for all and weekly for MisionesOnline, with no widening; the report states the low national power.
4. **Labeling protocol.** Recommended: a 60-note overlap with Cohen's kappa. This conflicts with `docs/def.md`, which lists inter-annotator agreement as out of scope, so it needs confirmation.
5. **Meaning of a label.** Recommended: valence of the text, not stance. The guide defines neutral and a "discard" label.
6. **Milestones.** The humans supply the list, dates and sources, choose the window (2 weeks) and set the minimum `n`.
7. **Scope vs. the 400-line budget.** Recommended: one change with two work units, or two changes if T5.1–T5.3 go well over 400 lines.

## Risks

- **Dependencies:** pysentimiento may not resolve or run on Python 3.12 or 3.14, pandas 3 or transformers 5. The torch wheels are large, so use the CPU index.
- **Model:** domain shift from tweets to news headlines.
- **Statistics:**
  - National outlets have weak milestone power, and the DNU window is truncated.
  - The drift in MisionesOnline's bajada and `fuente_externa` shares can look like a change in tone.
- **Data:** the dataset must stay stable, since a rerun changes ids and the sample. MisionesOnline cannot be refetched while it is challenged.
- **Process:** labeling is the critical path in human time.
