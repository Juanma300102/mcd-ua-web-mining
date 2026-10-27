import json
from datetime import date, datetime, timedelta, timezone

import pytest

from news_politica.sources import parse
from news_politica.sources.arc import build_catalog, fetch_story
from news_politica.sources.http import Blocked, ParseError
from news_politica.sources.infobae import INFOBAE
from news_politica.sources.lanacion import LANACION
from news_politica.sources.models import RawDoc

from .conftest import FakeRaw, fixture_text

OUTLETS = {"infobae": INFOBAE, "lanacion": LANACION}
FETCHED = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
NOTE = {
    "infobae": "https://www.infobae.com/politica/2024/03/25/las-negociaciones-por-la-ley-bases-entran-en-su-tramo-final-guillermo-francos-recibio-a-jorge-macri-y-a-cristian-ritondo/",
    "lanacion": "https://www.lanacion.com.ar/politica/javier-milei-ira-al-congreso-este-domingo-para-presentar-el-presupuesto-2025-nid10092024/",
}
SITEMAP_DAY = {"infobae": date(2023, 12, 10), "lanacion": date(2026, 7, 25)}


def story(medio, name, **changes):
    return json.loads(fixture_text(medio, f"{name}.json")) | changes


def story_doc(medio, name="story_normal", **changes):
    content = story(medio, name, **changes)
    url = OUTLETS[medio].site + content.get("canonical_url", "/politica/x/")
    return RawDoc(medio, url, url, 200, FETCHED, json.dumps(content, ensure_ascii=False))


# Catalog


@pytest.mark.parametrize("medio", ["infobae", "lanacion"])
def test_catalog_keeps_politica_urls_with_their_date(client, session, medio):
    outlet, day = OUTLETS[medio], SITEMAP_DAY[medio]
    session.routes[outlet.sitemap_url(day)] = FakeRaw(200, fixture_text(medio, "sitemap.xml"))
    catalog = build_catalog(client, outlet, start=day, end=day)
    assert len(catalog.entries) == 4
    assert all("/politica/" in e.url and e.url_date == day and e.sitemap_day == day for e in catalog.entries)
    assert all(e.medio == medio and e.lastmod for e in catalog.entries)
    assert catalog.failed_days == [] and catalog.dropped == 0


def test_url_listed_on_two_days_keeps_the_earlier(client, session):
    first = date(2023, 12, 10)
    for offset in (0, 1):
        session.routes[INFOBAE.sitemap_url(first + timedelta(days=offset))] = FakeRaw(200, fixture_text("infobae", "sitemap.xml"))
    catalog = build_catalog(client, INFOBAE, start=first, end=first + timedelta(days=1))
    assert len(catalog.entries) == 4
    assert {e.sitemap_day for e in catalog.entries} == {first}


def test_failing_sitemap_day_is_reported(client, session):
    first = date(2023, 12, 10)
    session.routes[INFOBAE.sitemap_url(first)] = FakeRaw(500)
    session.routes[INFOBAE.sitemap_url(first + timedelta(days=1))] = FakeRaw(200, fixture_text("infobae", "sitemap.xml"))
    session.routes[INFOBAE.sitemap_url(first + timedelta(days=2))] = FakeRaw(200, "<html>not xml")
    catalog = build_catalog(client, INFOBAE, start=first, end=first + timedelta(days=2))
    assert len(catalog.entries) == 4
    assert catalog.failed_days == [first, first + timedelta(days=2)]


def test_unparseable_url_date_is_dropped(client, session):
    day = date(2026, 7, 25)
    xml = ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           "<url><loc>https://www.lanacion.com.ar/politica/sin-fecha/</loc></url>"
           "<url><loc>https://www.lanacion.com.ar/politica/fecha-imposible-nid31022026/</loc></url>"
           "<url><loc>https://www.lanacion.com.ar/politica/con-fecha-nid25072026/</loc></url></urlset>")
    session.routes[LANACION.sitemap_url(day)] = FakeRaw(200, xml)
    catalog = build_catalog(client, LANACION, start=day, end=day)
    assert [e.url for e in catalog.entries] == ["https://www.lanacion.com.ar/politica/con-fecha-nid25072026/"]
    assert catalog.dropped == 2


def test_sitemap_urls():
    assert INFOBAE.sitemap_url(date(2023, 12, 11)) == "https://www.infobae.com/arc/outboundfeeds/sitemap/2023-12-11/"
    assert LANACION.sitemap_url(date(2023, 12, 31)) == (
        "https://www.lanacion.com.ar/sitemap-articles-from2023-12-31T00:00:00Z-to2024-01-01T00:00:00Z.xml")


# Fetching notes


@pytest.mark.parametrize("medio", ["infobae", "lanacion"])
def test_normal_note(client, session, medio):
    session.routes[NOTE[medio]] = FakeRaw(200, fixture_text(medio, "page.html"))
    doc = fetch_story(client, OUTLETS[medio], NOTE[medio])
    assert doc.error is None
    assert json.loads(doc.payload) == story(medio, "story_normal")
    assert "<script" not in doc.payload


def test_deleted_note(client, session):
    session.routes[NOTE["infobae"]] = FakeRaw(404, "not found")
    doc = fetch_story(client, INFOBAE, NOTE["infobae"])
    assert (doc.error, doc.payload, doc.status) == ("http_404", None, 404)


def test_page_without_story_json(client, session):
    session.routes[NOTE["lanacion"]] = FakeRaw(200, "<html><body>Nota</body></html>")
    assert fetch_story(client, LANACION, NOTE["lanacion"]).error == "no_story"


def test_page_whose_content_is_not_a_story(client, session):
    page = '<script>Fusion.globalContent={"type": "video", "_id": "X"};</script>'
    session.routes[NOTE["lanacion"]] = FakeRaw(200, page)
    assert fetch_story(client, LANACION, NOTE["lanacion"]).error == "no_story"


def test_redirect_out_of_the_section(client, session):
    session.routes[NOTE["infobae"]] = FakeRaw(200, "<html>home</html>", url="https://www.infobae.com/")
    doc = fetch_story(client, INFOBAE, NOTE["infobae"])
    assert doc.error == "redirected"
    assert doc.final_url == "https://www.infobae.com/"


def test_disallowed_note(client, session):
    session.routes["https://www.infobae.com/robots.txt"] = FakeRaw(200, "User-agent: *\nDisallow: /politica/\n")
    doc = fetch_story(client, INFOBAE, NOTE["infobae"])
    assert doc.error == "disallowed"
    assert session.requested(NOTE["infobae"]) == []


def test_challenge_is_not_a_per_note_loss(client, session):
    session.routes[NOTE["infobae"]] = FakeRaw(403, "<title>Just a moment...</title>", {"cf-mitigated": "challenge"})
    with pytest.raises(Blocked):
        fetch_story(client, INFOBAE, NOTE["infobae"])


# Parsing


def test_same_input_same_output():
    doc = story_doc("infobae")
    assert parse(doc) == parse(doc)


@pytest.mark.parametrize("medio", ["infobae", "lanacion"])
def test_note_fields(medio):
    article = parse(story_doc(medio))
    assert article.url == NOTE[medio]
    assert len(article.id) == 40
    assert article.medio == medio
    assert article.titulo and article.bajada and article.cuerpo
    assert "<" not in article.cuerpo and "&nbsp;" not in article.cuerpo
    assert article.seccion == "/politica"
    assert article.tags and article.fuente_externa == ""
    assert article.es_en_vivo is False
    assert article.fecha_scraping == FETCHED
    assert article.fecha_publicacion.utcoffset() == timedelta(hours=-3)


def test_publish_date_in_argentina_time():
    article = parse(story_doc("infobae", first_publish_date="2024-03-01T02:30:00Z"))
    assert article.fecha_publicacion.replace(tzinfo=None) == datetime(2024, 2, 29, 23, 30)


def test_author_and_missing_author():
    assert parse(story_doc("infobae")).autor == "Federico Galligani"
    assert parse(story_doc("infobae", credits={"by": []})).autor == ""
    assert parse(story_doc("infobae", credits=None)).autor == ""


def test_missing_title_raises():
    with pytest.raises(ParseError):
        parse(story_doc("lanacion", headlines={}))


def test_body_keeps_paragraphs():
    content = story("infobae", "story_normal")
    texts = [b for b in content["content_elements"] if b["type"] == "text" and b["content"]]
    assert parse(story_doc("infobae")).cuerpo.split("\n\n") == [b["content"] for b in texts]


def test_body_made_of_lists():
    content = story("lanacion", "story_lists")
    items = [i["content"] for b in content["content_elements"] if b["type"] == "list" for i in b["items"]]
    cuerpo = parse(story_doc("lanacion", "story_lists")).cuerpo
    assert len(items) >= 3
    assert all(item in cuerpo.split("\n\n") for item in items)


def test_infobae_live_blog():
    assert parse(story_doc("infobae", "story_live")).es_en_vivo is True


def test_lanacion_live_from_headline():
    article = parse(story_doc("lanacion", headlines={"basic": "Elecciones 2025, EN VIVO: los resultados"}))
    assert article.es_en_vivo is True


def test_lanacion_special_page():
    article = parse(story_doc("lanacion", "story_special"))
    assert story("lanacion", "story_special")["subtype"] == "9"
    assert article.cuerpo == ""


def test_raw_doc_with_error_raises():
    doc = RawDoc("infobae", NOTE["infobae"], NOTE["infobae"], 404, FETCHED, error="http_404")
    with pytest.raises(ParseError):
        parse(doc)


def test_unreadable_payload_raises():
    with pytest.raises(ParseError):
        parse(RawDoc("lanacion", "u", "u", 200, FETCHED, "<html>"))


def test_unknown_medio_raises():
    with pytest.raises(ParseError):
        parse(RawDoc("clarin", "u", "u", 200, FETCHED, "{}"))
