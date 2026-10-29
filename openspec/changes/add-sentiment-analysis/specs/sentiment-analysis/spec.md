## ADDED Requirements

### Requirement: The analysis text is the title plus the bajada
The analysis text of a note SHALL be `titulo + ". " + bajada`. When `bajada` is empty or blank, it SHALL be the title plus the first non-empty paragraph of the body, joined the same way. When both `bajada` and body are empty, it SHALL be the title alone. The body beyond its first paragraph SHALL NOT be scored.

#### Scenario: Note with bajada
- **WHEN** a note has title "Milei vetó la ley" and bajada "El Congreso insistirá"
- **THEN** its analysis text is "Milei vetó la ley. El Congreso insistirá"

#### Scenario: Note without bajada
- **WHEN** a note has an empty bajada and a body whose first paragraph is "El Gobierno confirmó el cambio."
- **THEN** its analysis text is the title, ". " and that paragraph, and no later paragraph

#### Scenario: Note with neither bajada nor body
- **WHEN** a note has a title and an empty bajada and body
- **THEN** its analysis text is the title

### Requirement: Sentiment is stored in long format per note and model
`sentimiento_noticias` SHALL be an unpartitioned asset that reads `noticias_politica`, leaves it unchanged and stores Parquet with one row per `(id, modelo)`. Each row SHALL hold `prob_pos`, `prob_neu`, `prob_neg`, `label` (the class with the highest probability) and `score = prob_pos − prob_neg`. `modelo` SHALL name the model that produced the row. The asset SHALL NOT use an outlet pool or any network access.

#### Scenario: One row per note and model
- **WHEN** the asset runs on 3 notes with a fake classifier
- **THEN** the output has 3 rows, one per `id`, all with the same `modelo`

#### Scenario: Probabilities, label and score
- **WHEN** a note gets probabilities (0.7, 0.2, 0.1) for (pos, neu, neg)
- **THEN** its row has `label` positive and `score` 0.6, and the three probabilities sum to 1

#### Scenario: Source dataset untouched
- **WHEN** the asset has run
- **THEN** `noticias_politica` is byte-identical to before

### Requirement: The alternative model depends on the hardware and is recorded
The baseline model SHALL be the `pysentimiento/robertuito-sentiment-analysis` checkpoint. The alternative model SHALL be a local LLM when an NVIDIA GPU is detected, otherwise mDeBERTa-v3 XNLI zero-shot. The model resource SHALL import torch lazily, use CUDA when it is available and fall back to CPU otherwise. Every output row SHALL carry the `modelo` that produced it, so runs from different machines stay distinguishable.

#### Scenario: GPU detected
- **WHEN** the resource selects the alternative model on a machine with an NVIDIA GPU
- **THEN** it selects the local LLM and rows are labeled with its name in `modelo`

#### Scenario: No GPU
- **WHEN** the resource selects the alternative model on a machine without an NVIDIA GPU
- **THEN** it selects mDeBERTa-v3 XNLI zero-shot on CPU and rows are labeled with its name in `modelo`

#### Scenario: Torch not installed
- **WHEN** the definitions are loaded in an environment without the `sentiment` group
- **THEN** loading succeeds, and torch is imported only when a model is first used

### Requirement: The labeling sample is seeded, balanced and split without overlap
The labeling sample SHALL hold 300 notes of `noticias_politica`, 100 per outlet, drawn with a fixed recorded seed from notes that are not live and have a non-empty title. It SHALL be split into two sheets of 150 notes, with no note in both. The sheets SHALL be labeled by an Anthropic model following `docs/guia-etiquetado.md`, not by the team members, and the model name and date SHALL be recorded in `docs/decision-sentimiento.md`. The committed labels file SHALL hold only `id` and label per note, with labels among positive, neutral, negative and discard; it SHALL NOT hold note text. The labeler SHALL see exactly the analysis text and nothing from the model output.

#### Scenario: Balanced draw
- **WHEN** the sample is built from the dataset with the recorded seed
- **THEN** it has 100 notes per outlet, none live and none with an empty title

#### Scenario: Reproducible draw
- **WHEN** the sample is built twice from the same dataset and seed
- **THEN** both runs return the same ids

#### Scenario: Disjoint split
- **WHEN** the sample is split into the two sheets
- **THEN** each part has 150 notes and the two parts share no `id`

#### Scenario: Committed labels carry no text
- **WHEN** the labels file is read
- **THEN** its columns are only `id` and the label

### Requirement: Each model is evaluated against the labels
The evaluation SHALL compute accuracy and macro F1 for every model on the labeled notes, overall and per outlet, and a confusion matrix per model. Notes labeled discard SHALL be excluded from the metrics. It SHALL also report the metrics for notes with and without bajada separately.

#### Scenario: Perfect agreement
- **WHEN** a model's labels equal the human labels on every kept note
- **THEN** its accuracy and macro F1 are 1.0

#### Scenario: Discarded notes
- **WHEN** 10 of the 300 labels are discard
- **THEN** the metrics are computed on the other 290

#### Scenario: Per-outlet metrics
- **WHEN** the evaluation runs
- **THEN** it reports macro F1 for each of the three outlets and for each model

### Requirement: Weekly tone is aggregated per outlet with its uncertainty
`evolucion_tono` SHALL hold one row per outlet and week with the number of notes `n`, the mean `score`, a confidence interval of that mean, and the share of each label. Live notes SHALL be excluded. All three outlets SHALL use the same weekly grain. A week with a single note SHALL report `n` and a mean, with the interval left empty because it is undefined.

#### Scenario: Weekly row
- **WHEN** an outlet has 4 non-live notes in a week with scores 0.2, 0.4, 0.0 and -0.2
- **THEN** its row has `n` 4 and mean score 0.1, and its label shares sum to 1

#### Scenario: Live notes excluded
- **WHEN** a week holds 3 live notes and 2 regular notes of an outlet
- **THEN** its row has `n` 2

#### Scenario: Single note
- **WHEN** a week holds one note of an outlet
- **THEN** its row has `n` 1 and no confidence interval

### Requirement: Milestones are compared with equal windows before and after
A versioned milestones file SHALL list each milestone with a name and date: DNU 70/2023, the Senate approval of Ley Bases (June 2024), the October 2025 legislative elections and one Misiones event. The comparison SHALL use the 2 weeks before and the 2 weeks after each milestone, per outlet, and report mean score, negative share and `n` for each side. A side with `n` below the minimum SHALL be marked "insufficient" and report no mean or share. A window cut by the dataset start (2023-12-10) SHALL be reported as truncated.

#### Scenario: Enough notes on both sides
- **WHEN** an outlet has more than the minimum `n` in both windows of a milestone
- **THEN** the table shows mean score, negative share and `n` for both sides

#### Scenario: Too few notes
- **WHEN** one side of a milestone has `n` below the minimum
- **THEN** that side is marked "insufficient" and shows `n` but no mean or share

#### Scenario: Window before the dataset start
- **WHEN** the DNU 70/2023 date (2023-12-20) makes its "before" window start before 2023-12-10
- **THEN** that window is reported as truncated

### Requirement: Sentiment assets log their progress at INFO
`sentimiento_noticias` and `evolucion_tono` SHALL log an INFO line at the start and an INFO summary line at the end. The summary of `sentimiento_noticias` SHALL include the model name and the number of notes scored; that of `evolucion_tono` SHALL include the number of weekly rows.

#### Scenario: Scoring logs
- **WHEN** `sentimiento_noticias` is materialized
- **THEN** the run log has an INFO start line and an INFO summary line with the model and the count

### Requirement: Sentiment tests run offline without torch
The sentiment tests SHALL use a fake classifier and a temporary data directory, without network access, and SHALL pass without the `sentiment` dependency group installed. The default `uv run pytest` and `uv run dg check defs` SHALL succeed in that environment.

#### Scenario: No torch, no network
- **WHEN** `uv run pytest` runs in an environment without torch or transformers and with networking disabled
- **THEN** every sentiment test passes

#### Scenario: Definitions check
- **WHEN** `uv run dg check defs` runs without the `sentiment` group
- **THEN** it succeeds
