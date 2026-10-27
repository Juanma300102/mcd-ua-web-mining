import json
from dataclasses import fields
from datetime import datetime, timedelta

import pytest

from news_politica.sources import check_losses
from news_politica.sources.http import TooManyLosses
from news_politica.sources.models import Article, RawDoc
from news_politica.sources.text import ART, article_id, html_to_text, to_art

from .conftest import FIXTURES

# Dataset schema, docs/def.md ("Esquema del dataset").
SCHEMA = ["id", "medio", "url", "fecha_publicacion", "titulo", "bajada", "cuerpo", "autor", "seccion", "tags",
          "fuente_externa", "es_en_vivo", "fecha_scraping"]


def test_article_has_the_schema_columns():
    assert [f.name for f in fields(Article)] == SCHEMA


def test_html_to_text():
    assert html_to_text("<p>Hola <b>mundo</b>&nbsp;y&amp;más</p>\n<p>  chau </p>") == "Hola mundo y&más chau"
    assert html_to_text("  sin   marcas ") == "sin marcas"
    assert html_to_text(None) == ""


def test_article_id_is_sha1_of_the_url():
    assert article_id("https://www.infobae.com/politica/x/") == article_id("https://www.infobae.com/politica/x/")
    assert len(article_id("https://a/")) == 40


@pytest.mark.parametrize("value", ["2024-03-01T02:30:00Z", "2024-03-01T02:30:00.402Z", "2024-03-01T02:30:00.87Z",
                                   "2024-03-01T02:30:00"])
def test_to_art(value):
    moment = to_art(value)
    assert moment.utcoffset() == timedelta(hours=-3)
    assert moment.replace(microsecond=0, tzinfo=None) == datetime(2024, 2, 29, 23, 30)
    assert moment.tzinfo == ART


def raw(error=None):
    return RawDoc("infobae", "u", "u", 200, datetime.now(ART), None if error else "{}", error)


def test_a_few_losses_are_counted():
    assert check_losses([raw("http_404")] * 3 + [raw()] * 97) == 3


def test_too_many_losses_fail():
    with pytest.raises(TooManyLosses):
        check_losses([raw("no_story")] * 40 + [raw()] * 60)


def test_no_documents_no_losses():
    assert check_losses([]) == 0


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def test_fixture_text_is_shortened():
    for path in FIXTURES.rglob("*.json"):
        longest = max((len(s) for s in _strings(json.loads(path.read_text()))), default=0)
        assert longest <= 200, path
    for path in [*FIXTURES.rglob("*.html"), *FIXTURES.rglob("*.xml")]:
        assert path.stat().st_size < 20_000, path
