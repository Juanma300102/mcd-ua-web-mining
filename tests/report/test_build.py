import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from news_politica.report.aggregates import build_payload, replace_data_block
from tests.report.test_aggregates import art, label_of, make

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "informe.html"
OPEN = '<script type="application/json" id="datos">'


def page(block="{}"):
    return f"<html><body><h1>Informe</h1>\n{OPEN}{block}</script>\n<script>draw()</script></body></html>"


def test_replace_changes_only_the_block():
    html = page('{"viejo": 1}')
    out = replace_data_block(html, {"nuevo": [1, 2]})
    before, after = html.split(OPEN), out.split(OPEN)
    assert before[0] == after[0]
    assert after[1].split("</script>", 1)[1] == before[1].split("</script>", 1)[1]
    assert json.loads(after[1].split("</script>", 1)[0]) == {"nuevo": [1, 2]}


def test_replace_twice_is_identical():
    once = replace_data_block(page(), {"b": 2, "a": "ñ"})
    assert replace_data_block(once, {"b": 2, "a": "ñ"}) == once
    assert "ñ" in once  # not escaped


def test_closing_tag_inside_data_is_escaped():
    out = replace_data_block(page(), {"titulo": "a </script> b"})
    assert out.count("</script>") == 2
    block = out.split(OPEN)[1].split("</script>", 1)[0]
    assert json.loads(block) == {"titulo": "a </script> b"}


@pytest.mark.parametrize("html", ["<html></html>", page() + page()])
def test_needs_exactly_one_block(html):
    with pytest.raises(ValueError, match="exactly one"):
        replace_data_block(html, {})


def test_script_exits_on_missing_data_and_keeps_page(tmp_path):
    target = tmp_path / "informe.html"
    target.write_text(page('{"x": 1}'), encoding="utf-8")
    env = {**os.environ, "DATA_DIR": str(tmp_path / "vacio"), "REPORT_PAGE": str(target)}
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_report.py")], env=env,
                            capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 1
    assert "sentimiento_noticias.parquet" in result.stderr
    assert target.read_text(encoding="utf-8") == page('{"x": 1}')


def test_page_reads_only_keys_the_payload_has():
    rows = [{"medio": m, "moment": art(2024, 6, d), "score": s} for m in ("infobae", "lanacion", "misionesonline")
            for d, s in ((1, -0.3), (2, 0.1), (20, 0.4))]
    scores, notes = make(rows)
    labels = pd.DataFrame({"id": notes["id"], "etiqueta": [label_of(r["score"]) for r in rows]})
    hitos = pd.DataFrame([{"hito": "H", "fecha": "2024-06-15", "alcance": "nacional"}])
    payload = build_payload(scores, notes, labels, hitos, "m")
    script = PAGE.read_text(encoding="utf-8").split(OPEN)[1].split("</script>", 1)[1]
    read = set(re.findall(r"\bD\.([a-z_]+)", script))
    assert read, "the page script reads no D.<key>"
    assert read <= set(payload), f"keys the page reads but the payload lacks: {sorted(read - set(payload))}"
