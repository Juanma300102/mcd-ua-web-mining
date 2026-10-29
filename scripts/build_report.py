"""Fill the data block of docs/informe.html from the stored Parquet files.

Usage: uv run python scripts/build_report.py

Reads data/sentimiento_noticias.parquet and data/noticias_politica.parquet (DATA_DIR overrides
data/, as in defs/io.py), anotaciones/etiquetas.csv and anotaciones/hitos.csv, and replaces only
the content of <script type="application/json" id="datos"> in docs/informe.html. Running it twice
leaves the page byte-identical. Missing inputs or a page without exactly one data block exit with
status 1 and leave the page untouched.
"""

import os
import sys
from pathlib import Path

import pandas as pd

from news_politica.defs.sentiment import MODELO_FINAL
from news_politica.report.aggregates import build_payload, replace_data_block

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))
PAGE = Path(os.environ.get("REPORT_PAGE", ROOT / "docs" / "informe.html"))


def main() -> int:
    inputs = {
        "scores": DATA_DIR / "sentimiento_noticias.parquet",
        "notes": DATA_DIR / "noticias_politica.parquet",
        "labels": ROOT / "anotaciones" / "etiquetas.csv",
        "hitos": ROOT / "anotaciones" / "hitos.csv",
        "page": PAGE,
    }
    missing = [str(path) for path in inputs.values() if not path.is_file()]
    if missing:
        print(f"Missing input files: {', '.join(missing)}", file=sys.stderr)
        return 1
    payload = build_payload(
        scores=pd.read_parquet(inputs["scores"]),
        notes=pd.read_parquet(inputs["notes"]),
        labels=pd.read_csv(inputs["labels"], dtype=str),
        hitos=pd.read_csv(inputs["hitos"], dtype=str),
        modelo=MODELO_FINAL,
    )
    html = PAGE.read_text(encoding="utf-8")
    try:
        updated = replace_data_block(html, payload)
    except ValueError as exc:
        print(f"{PAGE}: {exc}", file=sys.stderr)
        return 1
    if updated != html:
        PAGE.write_text(updated, encoding="utf-8")
    print(f"{PAGE.relative_to(ROOT) if PAGE.is_relative_to(ROOT) else PAGE}: data block "
          f"{'updated' if updated != html else 'unchanged'} ({MODELO_FINAL}, {payload['totales']['notas']} notes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
