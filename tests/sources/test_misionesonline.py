import json
from datetime import date, datetime, timedelta, timezone

import pytest

from news_politica.sources.http import ParseError, SourceError
from news_politica.sources.misionesonline import fetch_month, month_url, parse_post
from news_politica.sources.models import RawDoc

from .conftest import FakeRaw, fixture_text

PAGE = fixture_text("misionesonline", "posts_page.json")
JANUARY = date(2026, 1, 1)


def page(total_pages):
    return FakeRaw(200, PAGE, {"X-WP-Total": str(4 * total_pages), "X-WP-TotalPages": str(total_pages)})


def docs_by_id(client, session):
    session.routes[month_url(JANUARY, 1)] = page(1)
    return {json.loads(doc.payload)["id"]: doc for doc in fetch_month(client, JANUARY)}


def test_month_url_spans_the_month_in_site_time():
    assert "after=2026-01-01T00:00:00&before=2026-02-01T00:00:00" in month_url(date(2026, 1, 25), 1)
    assert "after=2025-12-01T00:00:00&before=2026-01-01T00:00:00" in month_url(date(2025, 12, 1), 2)
    assert month_url(JANUARY, 2).endswith("&page=2")


def test_month_spanning_several_pages(client, session):
    for number in (1, 2, 3):
        session.routes[month_url(JANUARY, number)] = page(3)
    docs = fetch_month(client, JANUARY)
    assert len(docs) == 12
    assert [len(session.requested(month_url(JANUARY, n))) for n in (1, 2, 3)] == [1, 1, 1]
    assert all(doc.error is None and "_links" not in json.loads(doc.payload) for doc in docs)


def test_empty_month(client, session):
    session.routes[month_url(JANUARY, 1)] = FakeRaw(200, "[]", {"X-WP-Total": "0", "X-WP-TotalPages": "0"})
    assert fetch_month(client, JANUARY) == []


@pytest.mark.parametrize("failure", [FakeRaw(500), FakeRaw(400, "{}")])
def test_failing_listing_page_raises(client, session, failure):
    session.routes[month_url(JANUARY, 1)] = page(3)
    session.routes[month_url(JANUARY, 2)] = failure
    with pytest.raises(SourceError):
        fetch_month(client, JANUARY)


def test_hand_written_excerpt_is_the_bajada(client, session):
    article = parse_post(docs_by_id(client, session)[1000001660730])
    assert article.bajada.startswith("En su viaje a Davos, el Presidente ratificó")


def test_automatic_excerpt_is_dropped(client, session):
    article = parse_post(docs_by_id(client, session)[1000001660985])
    assert article.bajada == ""
    assert article.cuerpo.startswith("En pleno verano")


def test_closing_source_is_the_external_outlet(client, session):
    docs = docs_by_id(client, session)
    assert parse_post(docs[1000001660730]).fuente_externa == "TN"
    assert parse_post(docs[1000001660985]).fuente_externa == ""


def post_doc(**changes):
    post = json.loads(PAGE)[0] | changes
    return RawDoc("misionesonline", post["link"], post["link"], 200, datetime(2026, 1, 27, tzinfo=timezone.utc),
                  json.dumps(post, ensure_ascii=False))


def test_source_trailer_is_removed():
    body = "<p>El Gobierno anunció cambios.</p><p>Fuente: Infobae 👉 MANTENETE INFORMADO</p>"
    assert parse_post(post_doc(content={"rendered": body})).fuente_externa == "INFOBAE"


def test_post_fields():
    article = parse_post(post_doc())
    assert article.medio == "misionesonline"
    assert article.url == "https://misionesonline.net/2026/01/25/milei-viaja-a-mar-del-plata-para-encabezar-la-derecha-fest/"
    assert article.fecha_publicacion.utcoffset() == timedelta(hours=-3)
    assert article.fecha_publicacion.replace(tzinfo=None) == datetime(2026, 1, 25, 23, 2, 39)
    assert article.seccion == "Nacionales, Política"
    assert "Javier Milei" in article.tags
    assert article.autor == "Redacción"
    assert article.es_en_vivo is False
    assert article.fecha_scraping == datetime(2026, 1, 27, tzinfo=timezone.utc)
    assert parse_post(post_doc()) == article


def test_missing_title_raises():
    with pytest.raises(ParseError):
        parse_post(post_doc(title={"rendered": ""}))
