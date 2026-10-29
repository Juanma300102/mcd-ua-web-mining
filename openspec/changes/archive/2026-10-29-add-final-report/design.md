## Context

Phase 5 left two Parquet files in `data/`: `sentimiento_noticias` (9,261 notes × 3 models, long format) and `evolucion_tono` (weekly tone per model and outlet). The sentiment assets ran on a teammate's WSL machine with a GPU; the files were copied to this machine, and their notes match the frozen `noticias_politica` (SHA-256 `ab5de8cb…`). `notebooks/05_sentimiento.ipynb` has the evaluation, the weekly charts and the milestone table, written for the team.

Exploration on 2026-10-29 found the story the report tells (robertuito, live notes excluded):

| Finding | Numbers |
|---|---|
| Tone barely moved | National outlets stay between -0.25 and -0.40 every half-year from 2023-S2 to 2026-S2 |
| Traditional is the most negative, provincial the lightest | La Nación -0.35 (46 % negative), Infobae -0.28 (40 %), MisionesOnline -0.03 (25 %) |
| The ordering holds for all three models | mdeberta -0.24 / -0.15 / +0.18; qwen -0.13 / -0.07 / +0.04 (La Nación / Infobae / MisionesOnline) |
| MisionesOnline sounds national when it reproduces national notes | own notes ≈ 0.01, notes with `fuente_externa` ≈ -0.24; holds for bajada-only notes and for all three models |
| Milestones move little | 3 of 9 changes have an interval that excludes zero: DNU at MisionesOnline (-0.23), Ley Bases at Infobae (+0.67, 16 vs 12 notes), 2025 elections at MisionesOnline (+0.16) |

Constraints: the audience is mixed (technical and not), the team docs are in Spanish, `docs/bitacora-fases.html` already set the visual system, the delivery is close, and no new dependencies are wanted.

## Goals / Non-Goals

**Goals:**
- A report anyone can read top to bottom, with each chapter answering one question of `docs/def.md`.
- Numbers that cannot drift from the data: computed by tested code and embedded, never typed by hand.
- One self-contained page plus two images, rebuildable with one command.

**Non-Goals:**
- Changing the pipeline, the models or any stored output.
- A report asset in Dagster, a PDF or slides.
- New statistics beyond what Phase 5 defined (no break-point models, no new significance tests).

## Decisions

### 1. Hand-written HTML page with one embedded JSON block, rewritten by a script

The narrative, layout and chart code are written by hand in `docs/informe.html`. One element, `<script type="application/json" id="datos">…</script>`, holds every number. `scripts/build_report.py` computes the aggregates and replaces only the content of that element (located by its id with a regular expression anchored on the opening and closing tags). The chart code reads the block with `JSON.parse` and draws inline SVG.

Alternatives considered:
- **Numbers typed into the HTML.** Fastest, but a copied number can be wrong and nothing catches it; rejected.
- **A Jinja template rendered into the page.** Splits the page into a template and an output that both live in the repo, and adds a dependency; rejected.
- **Charts pre-rendered as PNG from matplotlib (as in the notebook).** Breaks dark mode and phone layout and looks like a notebook, not a story; kept only for the weekly figure in the annex if needed.

### 2. Aggregations in a pure module, reusing Phase 5 code

`src/news_politica/report/aggregates.py` holds pure functions over the two DataFrames:

- `outlet_summary(scores, notes, modelo)`: `n`, mean score and label shares per outlet.
- `outlet_means_by_model(scores, notes)`: mean score per outlet for every model.
- `monthly_tone(scores, notes, modelo)`: `n`, mean and 95 % t interval per outlet and ART month.
- `provincial_split(scores, notes)`: MisionesOnline own vs reproduced notes, `n` and mean per model.
- `milestones(scores, notes, hitos, modelo)`: calls `compare_milestones` and adds a `claro` flag (interval excludes zero).
- `volume(notes)`: notes per outlet and month (intro chart).
- `build_payload(...)`: assembles everything into one JSON-serializable dict with a `generado` date and the model name.

Exclusions and the interval come from `news_politica.sentiment.tone` (its eligibility rule and `_half_width`), so the report and `evolucion_tono` count the same notes. Using private helpers across modules is a small smell; the alternative (copying the rules) is worse. If the reviewer prefers, `tone.py` can expose `eligible` and `half_width` without the underscore, which does not change behaviour.

Alternatives considered: computing in the notebook and exporting JSON (not testable, depends on running cells in order); reading `evolucion_tono.parquet` and resampling weeks to months (weeks cross month edges, so monthly means would be wrong).

### 3. Monthly grain in the story, weekly only in the annex

Infobae has data in 77 weeks (its catalog reads the sitemaps of days 5 and 20), La Nación in 147 and MisionesOnline in 148, and Arc outlets have ~30 notes per month. A weekly line jumps on noise, and a non-technical reader reads jumps as events. Monthly points per outlet, with a light band for the interval, show the real message (flat) honestly. The annex can mention the weekly asset for technical readers.

### 4. Chart set and what each one says

| Chapter | Chart | Why this form |
|---|---|---|
| Hero | Horizontal "thermometer" from -1 to +1 with one dot per outlet | Answers the comparison in one glance before any reading |
| Intro: volume | Small multiples, notes per month per outlet | Shows the scale and that MisionesOnline is complete while Arc is sampled |
| Pipeline | Two screenshots with numbered callouts | "Assembly line" metaphor; shows completeness (34 months, 0 failed) |
| Q1 over time | Monthly lines per outlet, interval band, milestone rules | Flatness is visible; milestones in context |
| Q2 outlets | 100 % stacked bars neg/neu/pos per outlet, plus the three-model dots | Shares are easier than means for non-technical readers; dots prove robustness |
| Q3 milestones | Before → after slope pairs, 3 milestones × 3 outlets; colour only when `claro` | Direction and size at a glance; grey communicates "not distinguishable" |
| Q4 provincial | Dot plot: La Nación, Infobae, MisionesOnline own, MisionesOnline reproduced | The twist of the story in one row |

Colours: the per-outlet tokens of the phase log (`--s1` Infobae, `--s2` La Nación, `--s3` MisionesOnline, as the phase log uses them); neutral grey (`--s-est`) for "not distinguishable"; a diverging red-grey-green only for the label shares.

### 5. Screenshots committed as PNG files next to the page

`docs/img/dagster-lineage.png` and `docs/img/dagster-particiones.png`, taken from the local Dagster UI (`scripts/dagster-up.sh`, `OLLAMA=off`) at 1400 px wide, cropped to the graph and partition bar, referenced with relative paths. Base64 inside the HTML would keep one file but makes the page diff unreadable; the phase log had no images, so this sets the convention. When the report is published as an Artifact, the two images go in its `files`.

The local UI shows `sentimiento_noticias` and `evolucion_tono` as never materialized. The caption says so; rematerializing here would overwrite `sentimiento_noticias.parquet` with robertuito only (the default config) and lose the other two models.

### 6. Tone of the text

Each chapter: a heading that is the answer, one chart, one paragraph of "what this means", and at most one "for the curious" sentence. Numbers in the narrative are rounded (one decimal for scores, whole percentages). Score is explained once as a "nota de -1 a +1". Spanish, plain register, no jargon outside the annex.

## Risks / Trade-offs

- [Private helpers of `tone.py` used from `report/`] → Accept, or make them public in the same PR with no behaviour change; tests cover both modules.
- [Regex replacement of the data block breaks if the tag is edited by hand] → Anchor on `id="datos"`, fail loudly if not exactly one match, and test the round trip (replace twice = same bytes).
- [Hand-written SVG code is the largest part of the diff and is not unit-tested] → A key-contract test checks that every key the page reads exists in the payload; manual check in the browser at desktop and 375 px, light and dark.
- [Readers over-read the Ley Bases jump at Infobae] → The text names the sample (16 vs 12 notes) and calls it a hint, not a finding.
- [Report size exceeds the 400-line review budget] → The HTML is mostly prose and markup; see the tasks forecast for the size exception.

## Migration Plan

Not applicable: the change only adds files and edits docs. Rollback is reverting the PR.

## Open Questions

- Whether to publish the report as a claude.ai Artifact for sharing, in addition to committing it (decide at the end of apply; publishing is outward-facing).
- Whether `tone.py` helpers become public (decide in review).
