## Why

Phases 1–5 are done: `noticias_politica` (9,261 notes) is built, every note has a sentiment score, robertuito was chosen, and `evolucion_tono` and the milestone comparison exist. The questions in `docs/def.md` are still unanswered in a form anyone can read: the results live in a notebook and in decision docs written for the team. Phase 6 (T6.2) is the report. It has to work for a non-technical reader (a classmate, a professor, a journalist) and for a technical one, so it is told as a story with one finding per chapter, and the technical detail goes in a collapsible annex.

## What Changes

- A narrative HTML report in Spanish, `docs/informe.html`, in the visual system of `docs/bitacora-fases.html` (fonts, colour tokens, one fixed colour per outlet, dark mode, phone width). Its chapters follow the questions in `docs/def.md`:
  - Intro: the question, what was read (volume per outlet and month), and an early note that tone is not stance.
  - The data pipeline: two annotated Dagster UI screenshots (asset lineage, and the 34 monthly partitions of a `raw_*` asset).
  - Main question (a), change over time: monthly tone per outlet with the milestones marked.
  - Main question (b), digital vs traditional vs provincial: mean tone and the negative/neutral/positive share per outlet.
  - Secondary question, milestones: before/after per milestone and outlet, with clear changes highlighted and the rest shown as "not distinguishable".
  - Secondary question, provincial tone: MisionesOnline's own notes vs the notes it reproduces from national outlets (`fuente_externa`), with the three models shown to agree.
  - Closing: the three answers in one sentence each, what the report does not say, and a collapsible technical annex (pipeline, robots.txt, model evaluation, confidence intervals, how to rebuild).
- A small, pure aggregation module that computes every number and series in the report from `data/sentimiento_noticias.parquet` and `data/noticias_politica.parquet`. It reuses `compare_milestones` and the tone exclusions from `news_politica.sentiment.tone`, and it is tested offline.
- A build script that runs the aggregations and writes them as one JSON block inside `docs/informe.html`. The page draws its charts from that block as inline SVG, so the numbers are never copied by hand.
- The screenshots, committed under `docs/img/`.
- Doc fixes: `docs/decision-sentimiento.md` says Infobae and La Nación both have data in 77 weeks, but La Nación has 147 (only Infobae's catalog reads two days a month). `docs/def.md` marks Phase 5 as closed and records Phase 6. `README.md` says how to rebuild the report.

## Non-goals

- New scraping, rescoring, or widening the Arc sample.
- New models, or changes to `sentimiento_noticias`, `evolucion_tono` or `compare_milestones`.
- A Dagster asset for the report: it is a document built from stored Parquet files, not part of the pipeline.
- Stance detection, time-series or break-point models (out of scope in `docs/def.md`).
- A slide deck, a PDF, or an English version.
- Charting libraries or a JavaScript build step.
- Quoting notes: no title, bajada or body is reproduced in the page.

## Capabilities

### New Capabilities
- `final-report`: the narrative report, its chapters mapped to the questions in `docs/def.md`, the aggregations behind every number, the build script that embeds them, the Dagster screenshots, the limitations it must state, and the offline tests.

### Modified Capabilities
<!-- None: the report reads the sentiment outputs as they are; `sentiment-analysis` requirements do not change. -->

## Impact

- New: `src/news_politica/report/` (aggregations), `scripts/build_report.py`, `docs/informe.html`, `docs/img/dagster-*.png`, `tests/report/`.
- Changed: `docs/decision-sentimiento.md` (weeks per outlet), `docs/def.md` (Phase 5 closed, Phase 6), `README.md` (rebuild command).
- Not changed: assets, resources, `src/news_politica/sentiment/`, `src/news_politica/sources/`, the Parquet files.
- Dependencies: none new (pandas, scipy and the standard library are enough).
- Network: none. Building the report needs the two Parquet files in `data/`; the tests use synthetic frames.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| A non-technical reader takes "more negative" as "opposition outlet" | High | Say "tone is not stance" before the first finding, and again in the limitations |
| Weak samples are read as strong findings (Ley Bases at Infobae: 16 vs 12 notes) | Med | Milestone chart greys out changes whose interval includes zero; the text names the sample size of any highlighted change |
| Monthly series for the Arc outlets rest on ~30 notes per month | Med | Monthly grain instead of weekly in the story; a light band for the interval; the weekly series stays in the annex |
| "All news" in the objective is read literally | Med | The intro says that Infobae and La Nación are a sample of 30 notes per month and MisionesOnline is complete |
| Silver labels make the model evaluation look stronger than it is | Med | The annex states the labels came from Claude Opus 5.5, with no human review |
| The sentiment assets show as never materialized in the local Dagster UI (they ran on the GPU machine) | High | Keep the screenshot and say so in the caption; it also shows the results travelled as files between two machines |
| Hand-written chart code drifts from the numbers | Low | All numbers come from the embedded JSON; a test checks the JSON block's keys against what the page reads |

## Rollback Plan

The change only adds a document, its assets, a pure module and a script, and edits three docs. Revert the PR; the pipeline and the data are untouched.

## Success Criteria

- `docs/informe.html` opens offline in a browser and answers the main question and both secondary questions of `docs/def.md`, each in a chapter whose heading states the answer.
- Every number in the page comes from the embedded JSON, and `uv run python scripts/build_report.py` rebuilds it from `data/`.
- The limitations (sample, silver labels, tone is not stance, robertuito trained on tweets, agency notes, robots.txt) are stated.
- `uv run pytest` and `uv run dg check defs` pass.
