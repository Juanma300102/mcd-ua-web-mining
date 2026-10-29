# Tasks: Narrative final report (Phase 6)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1,100 authored (WU1 ~420, WU2 ~650); PNG files not counted |
| 400-line budget risk | High |
| Chained PRs recommended | No |
| Suggested split | Single PR with 5 commits (below); WU2 is mostly Spanish prose and SVG markup |
| Delivery strategy | single-pr |
| Chain strategy | size-exception |

Decision needed before apply: Yes
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: High

The strategy is `single-pr`, so the humans must accept `size:exception` before apply, or ask for a split at the WU1/WU2 boundary (PR 1: aggregations, script and doc fixes; PR 2: the page and screenshots).

### Per-work-unit estimate

| Unit | Code | Tests | Docs / page / other | Total |
|------|------|-------|---------------------|-------|
| WU1 | ~200 | ~170 | ~50 | ~420 |
| WU2 | ~250 (chart JS) | ~30 | ~370 (HTML, CSS, prose) | ~650 |
| Total | ~450 | ~200 | ~420 | ~1,070 |

### Proposed commit boundaries

| Commit | Contents | Tasks |
|--------|----------|-------|
| C1 | `docs`: fix the weeks per outlet in `decision-sentimiento.md`, close Phase 5 in `def.md` | 1.x |
| C2 | `feat(report)`: aggregation module and tests | 2.x |
| C3 | `feat(report)`: build script, data-block round trip and tests | 3.x |
| C4 | `docs(report)`: Dagster screenshots | 4.x |
| C5 | `docs(report)`: the narrative page, README and close-out | 5.x, 6.x |

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| WU1 | Every number of the report computed by tested code | PR 1 (or the single PR) | Commits C1–C3; base: `main` |
| WU2 | The page a reader sees | PR 2 (or the single PR) | Commits C4–C5; needs WU1's payload keys |

## 1. Doc fixes (C1)

- [x] 1.1 `docs/decision-sentimiento.md`, "Dataset congelado": the limitation says Infobae and La Nación both have data in 77 of about 147 weeks. Correct it: only Infobae (its catalog reads the sitemaps of days 5 and 20) has 77 weeks; La Nación has 147 (full catalog, 30 notes sampled per month across all days) and MisionesOnline 148. Check: the numbers match `evolucion_tono.parquet` (`groupby(['modelo','medio']).size()`).
- [x] 1.2 `docs/def.md`: in "Estado y decisiones de la fase 5" replace the "falta la evaluación…" status with the closed status (robertuito chosen, both assets materialized on the GPU machine, Parquet files shared); in "Pasos de ejecución" mark step 5 done and step 6 "en curso, cambio OpenSpec `add-final-report`"; in "Riesgos y decisiones abiertas" drop the model from "A decidir". Spanish.

## 2. Aggregation module (C2)

- [x] 2.1 Create `src/news_politica/report/__init__.py` (docstring) and `src/news_politica/report/aggregates.py` with `outlet_summary`, `outlet_means_by_model`, `monthly_tone`, `provincial_split`, `milestones`, `example_headlines`, `volume` and `build_payload` per design decision 2. Reuse the eligibility rule and interval of `news_politica.sentiment.tone` (live notes, NaN scores and null dates excluded; t interval only for `n >= 2`) and `compare_milestones` unchanged. Months are ART calendar months keyed `YYYY-MM`. `milestones` adds `claro = ic_inf > 0 or ic_sup < 0` (False when the interval is NaN). `example_headlines` picks, per label, the labeled note where the final model agrees with the label with the highest probability for that label, shortest title on ties, then lowest id; returns `id, medio, titulo, label, score`. The payload is plain JSON types (no NaN: use `null`), floats rounded to 3 decimals.
- [x] 2.2 Create `tests/report/__init__.py` and `tests/report/test_aggregates.py` with synthetic frames covering the spec scenarios: monthly point (0.2, 0.4, 0.0, -0.2 plus one live note gives `n` 4, mean 0.1), month with one note (mean, null interval), shares sum to one (2/1/1 gives 0.5/0.25/0.25), provincial split by `fuente_externa` (3 own, 2 "TN"), milestone `claro` for an interval excluding zero and not for (-0.33, 0.27), insufficient window passes through with no means, deterministic headlines (same pick after shuffling rows), payload is JSON-serializable with no NaN. Check: `uv run pytest tests/report`.

## 3. Build script and data block (C3)

- [x] 3.1 Create `scripts/build_report.py`: reads `data/sentimiento_noticias.parquet`, `data/noticias_politica.parquet`, `anotaciones/etiquetas.csv` and `anotaciones/hitos.csv` (paths relative to the repo root, `DATA_DIR` honoured as in `defs/io.py`), uses `MODELO_FINAL`, calls `build_payload`, and replaces the content of the single `<script type="application/json" id="datos">` element in `docs/informe.html` with the JSON (sorted keys, `ensure_ascii=False`, 2-space indent). Exits non-zero naming the missing input file, or when the page does not have exactly one `datos` element, without touching the page. Put the replace logic in a function in `news_politica.report` (e.g. `replace_data_block(html, payload) -> str`) so it is testable.
- [x] 3.2 `tests/report/test_build.py`: `replace_data_block` changes only the block, applying it twice gives identical text, and zero or two `datos` elements raise. Spec scenarios: rebuild replaces only the data block; missing data (script run in a subprocess with an empty `DATA_DIR` exits non-zero and leaves a temporary page unchanged). Check: `uv run pytest tests/report`.

## 4. Dagster screenshots (C4)

- [x] 4.1 Start the local Dagster UI (`OLLAMA=off scripts/dagster-up.sh`), open the global asset lineage at 1400 px wide, dismiss any dialog, and capture the graph area only (no side navigation) to `docs/img/dagster-lineage.png`. The two sentiment assets show as not materialized; keep them in the shot.
- [x] 4.2 Capture the partitions bar and the "Materialized (34) · Failed (0) · Missing (0)" filter row of `raw_misionesonline` to `docs/img/dagster-particiones.png`. Check: both PNGs under ~400 KB each, legible at 700 px wide.

## 5. Narrative page (C5)

- [x] 5.1 Create `docs/informe.html` from the phase log's head (fonts, `:root` colour tokens with the light/dark blocks, body padding, reading column), with an empty `datos` block, and run `scripts/build_report.py` to fill it.
- [x] 5.2 Write the narrative sections in Spanish per design decision 6, with headings that state the answers: hero (title as the question, one-line scope, thermometer), intro (what was read: volume chart and the "30 per month vs complete" note; how a model reads: three headlines on the -1..+1 scale; the sentence that tone is not stance), pipeline (the two screenshots with numbered captions; the lineage caption says the sentiment assets ran on the GPU machine), chapters Q1–Q4, limitations, closing with the three one-sentence answers.
- [x] 5.3 Write the chart code (vanilla JS, inline SVG, reads only `JSON.parse(document.getElementById('datos').textContent)`): thermometer, volume small multiples, headline scale, monthly lines with interval band and milestone rules, stacked label shares with the three-model dots, milestone slope pairs (colour only when `claro`, "pocas notas" when insufficient), provincial dot plot. Every chart has a title, axis labels in Spanish and a text alternative (`<title>`/`aria-label`).
- [x] 5.4 Write the technical annex as a `<details>` closed by default: pipeline and assets, robots.txt and the access route, model evaluation table (accuracy and macro F1 of the three models, copied from the payload, which carries the numbers from `docs/decision-sentimiento.md` as constants in `build_payload` with a comment pointing to the doc), silver labels, intervals (t for monthly means, Welch for milestones, 14-day windows, `N_MIN`), the rebuild command.
- [x] 5.5 Add a key-contract test in `tests/report/test_build.py`: extract the `D.<key>` / `datos.<key>` names the page script reads (simple regex over `docs/informe.html`) and assert each is a top-level key of `build_payload` on synthetic data. Spec scenario: page and data agree on keys.
- [x] 5.6 Manual check in the built-in browser: desktop width and 375 px, light and dark; no horizontal scroll; annex collapsed on load; the stance sentence appears before chapter 1; the screenshots load. Fix what fails.

- [x] 5.7 Technology section (requested 2026-10-29): step-by-step walk through the process with the technologies that act in each step and their role, the per-outlet scraping routes, the three models with their accuracy from the data block, and a table explaining each Dagster asset; drop the silver-label bullet from the limitations (the annex keeps the caveat).

- [x] 5.8 Drop the "Cómo le pone nota una máquina a una noticia" section (requested 2026-10-29): remove the three example headlines from the page, `example_headlines` and its test; keep the "tono no es postura" note at the end of the "Qué leímos" section and explain the -1..+1 scale in the hero caption.

## 6. Docs and close-out (C5)

- [x] 6.1 `README.md`: a short "Report" section: what `docs/informe.html` is, the inputs it needs in `data/`, and `uv run python scripts/build_report.py`.
- [x] 6.2 Final check: `uv run pytest` and `uv run dg check defs` pass without the `sentiment` group and with an empty `DATA_DIR`; re-running `scripts/build_report.py` leaves `docs/informe.html` byte-identical. Report the actual results.
- [x] 6.3 **[HUMAN]** Decide whether to publish the report as a claude.ai Artifact (with the two images in `files`) for sharing; publish only on an explicit yes. Decided 2026-10-29: not published; the report is committed to `main` in `docs/`.

## Dependency notes

- 2.x before 3.x (the script calls `build_payload`); 3.x before 5.1 (the page is filled by the script).
- 4.x is independent of 2.x/3.x and can run any time Docker is up.
- 5.5 needs the page script from 5.3.
- Commits follow Conventional Commits with no AI attribution trailer (`openspec/config.yaml`).
