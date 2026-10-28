# news-politica

Dataset and sentiment analysis of Argentine political news (Infobae, La Nación and MisionesOnline) published since 2023-12-10. The project definition (objective, data sources, schema and plan) is in [`docs/def.md`](docs/def.md).

**Team:** Carlos Aular, Juan Martin Pedrozo.

## Requirements

- [uv](https://docs.astral.sh/uv/) (Python 3.11+; the repo pins 3.12 in `.python-version`)
- Docker with Compose v2.1+ (Postgres for Dagster's run, schedule and event storage; the start script uses `docker compose up --wait`)

## Setup

```bash
uv sync
cp .env.example .env   # optional: change credentials or the Postgres port
```

## Run Dagster

```bash
scripts/dagster-up.sh
```

The script starts Postgres with `docker compose`, checks the connection, validates the definitions and opens the Dagster UI at http://127.0.0.1:3000. Postgres listens on `127.0.0.1` only, host port `5434` by default (`POSTGRES_PUBLISH_PORT` in `.env`).

If Postgres rejects the credentials after you change `.env`, the Docker volume still has the old password. Run `docker compose down -v` (this deletes the local Dagster history) and try again.

## Backfill

The dataset covers 2023-12-10 to the cut-off, 2026-09-30 23:59 ART. Run it outside Claude Code's sandbox, with Docker up. This is a proof of concept: each Infobae and La Nación month fetches a stable sample of 30 notes (`SAMPLE_PER_MONTH` in `defs/assets.py`), and the catalogs read only the sitemaps of days 5 and 20 of each month (`SITEMAP_DAYS`), so each outlet takes well under an hour at 1 request / 2 s instead of ~14 h; MisionesOnline is complete and takes ~15 min.

1. `scripts/dagster-up.sh`, then in the UI (Assets) select every asset and click **Materialize all**, all partitions. Dagster runs an asset backfill: the two catalogs (~35 min each), then one run per month and outlet, then `noticias_politica`.
2. Each outlet has its own pool with limit 1 (`dagster.yaml`), so at most one run per outlet is in progress; the three outlets run in parallel. `scripts/dagster-up.sh` creates the three pools before starting Dagster: on a fresh database, Dagster 1.13.27 lets the first runs of a pool start together before applying `default_limit`. Check with `dagster instance concurrency get --all`.
3. A month that fails with a transient error is retried twice, 5 min apart. A `Blocked` (anti-bot challenge) or `TooManyLosses` failure is not retried: cancel that outlet's remaining runs in the UI (Runs, filter by the asset) instead of letting them fail one by one, and check the site before re-launching.
4. Failed months can be re-launched from the asset's partitions view. `noticias_politica` skips months that are missing, so it can be materialized from a partial backfill.

Files land in `data/<asset>.parquet` and `data/raw_<medio>/<YYYY-MM-DD>.parquet` (`DATA_DIR` overrides `data/`).

## Sentiment analysis

The sentiment code is in `src/news_politica/sentiment/`; the assets are `sentimiento_noticias` (one row per note and model, in long format) and `evolucion_tono` (weekly tone per model and outlet). Both read `data/noticias_politica.parquet`, so run the backfill first. The decisions and the labeling guide are in [`docs/decision-sentimiento.md`](docs/decision-sentimiento.md) and [`docs/guia-etiquetado.md`](docs/guia-etiquetado.md).

### Install the models

The models live in their own dependency group, so `uv sync` and the tests never install torch:

```bash
uv sync --group sentiment
```

On Linux and Windows the group takes torch from the CPU index (`pytorch-cpu` in `pyproject.toml`, not the much larger CUDA build); macOS uses PyPI. `robertuito` (pysentimiento) and `mdeberta-xnli` download their weights from Hugging Face the first time they run. The Dagster definitions load without the group: a model is only imported when an asset or the notebook asks for it, and a missing library fails the run with the command to fix it.

### Ollama (optional, GPU alternative)

The alternative model, `qwen2.5-7b`, runs in [Ollama](https://ollama.com) and is reached over HTTP, so it adds no Python package:

```bash
ollama serve                       # leave it running
ollama pull qwen2.5:7b-instruct
export OLLAMA_HOST=http://localhost:11434   # optional; this is the default
```

`SentimentModels.alternative()` picks `qwen2.5-7b` only when Ollama is reachable, the model is pulled and `GET /api/ps` reports `size_vram > 0` (the model runs on the GPU). Otherwise it logs a warning and falls back to `mdeberta-xnli`, because the LLM on CPU is too slow for the whole dataset. Naming `qwen2.5-7b` explicitly never falls back: if Ollama is down the run fails with the fix. A generation that times out is not retried; connection errors and HTTP 429/5xx are retried up to 3 times.

### Draw the labeling sample

The 300-note sample (100 per outlet, split between annotators `a` and `b`) is drawn in section 1 of `notebooks/05_sentimiento.ipynb`:

```bash
uv sync --group notebooks --group sentiment
uv run --group notebooks jupyter lab notebooks/
```

Draw it only from the complete, frozen dataset that the team shares. The sample depends on the note ids present, so a partial `data/noticias_politica.parquet` gives a different sample; the notebook fails if an outlet has fewer eligible notes than `PER_MEDIO`. The sheets (`data/etiquetado/anotador_{a,b}.csv`) contain scraped text and stay out of git, and `export_sheets` refuses to overwrite sheets that already exist. After both members fill them in, the merge cell validates them and writes `anotaciones/etiquetas.csv` (`id, anotador, etiqueta`, no text), the only labeling file that is committed. Commit the notebook without outputs.

### Materialize the assets

In the Dagster UI, select `sentimiento_noticias` and click **Materialize**; the Launchpad takes the models to score:

```yaml
ops:
  sentimiento_noticias:
    config:
      modelos: [robertuito]   # robertuito (default), mdeberta-xnli, qwen2.5-7b
```

From the command line (`DAGSTER_HOME` as in `scripts/dagster-up.sh`):

```bash
export DAGSTER_HOME="$PWD/src/news_politica/dagster_home"
uv run dagster asset materialize -m news_politica.definitions --select sentimiento_noticias \
  --config-json '{"ops": {"sentimiento_noticias": {"config": {"modelos": ["robertuito"]}}}}'
uv run dagster asset materialize -m news_politica.definitions --select evolucion_tono
```

Listing several models scores each one and writes one row per `(id, modelo)`. `evolucion_tono` leaves out live notes, unscored notes, scores without a note and notes without a date, and the run reports how many of each. The milestones used for the before and after comparison are in `anotaciones/hitos.csv`.

## Checks

```bash
uv run pytest
uv run dg check defs
```

## Source exploration notebooks

`notebooks/` holds the phase 2 exploration of each outlet; the decisions are in [`docs/decision-fuentes.md`](docs/decision-fuentes.md). Jupyter lives in its own dependency group:

```bash
uv sync --group notebooks
uv run --group notebooks jupyter lab notebooks/
```

Every request goes through `notebooks/probe.py` (robots.txt check, 2 s between requests to a host, stops on an anti-bot challenge) and is cached in `data/probe_cache/`. To re-run a notebook from the cache only, without touching the sites:

```bash
cd notebooks && PROBE_OFFLINE=1 uv run --group notebooks jupyter nbconvert --to notebook --execute --inplace 02_infobae.ipynb
```

The cache from the phase 2 run (~175 MB of the outlets' pages) was deleted when phase 3 closed, after the test fixtures were built from it. `PROBE_OFFLINE=1` therefore fails until a notebook has run online once and filled the cache again; delete `data/probe_cache/` when you no longer need it.

`notebooks/04_eda.ipynb` is the EDA of the dataset (T4.4). It only reads `data/noticias_politica.parquet` and `data/raw_lanacion/`, so it needs the backfill but no network:

```bash
cd notebooks && uv run --group notebooks jupyter nbconvert --to notebook --execute --inplace 04_eda.ipynb
```

## Layout

```
docker-compose.yaml        # Postgres for Dagster storage
scripts/dagster-up.sh      # starts Postgres + Dagster
src/news_politica/
  definitions.py           # loads everything under defs/
  dagster_home/dagster.yaml
  defs/                    # assets.py (catalogs, raw_* by month, noticias_politica), sentiment.py, io.py (Parquet, client, models)
  sources/                 # scraping clients: HTTP client, one module per outlet, parse()
  sentiment/               # analysis text, labeling, classifiers, scoring, evaluation, weekly tone
tests/
  fixtures/sources/        # trimmed responses from the phase 2 cache (build_fixtures.py)
notebooks/                 # phase 2 source exploration (probe.py, arc.py, one notebook per outlet), 05 sentiment
anotaciones/               # etiquetas.csv (human labels, no text), hitos.csv (political milestones)
docs/                      # project definition, source and sentiment decisions, labeling guide, bitacora-fases.html (phases 1-4 report)
odd/tasks/                 # task tracking
data/                      # Parquet output (gitignored)
```
