"""Shared client for the Arc XP outlets (Infobae, La Nación): T3.3 and T3.4.

Notes are listed from daily sitemaps into a catalog and fetched one by one; the
raw document keeps the story JSON that each page embeds as Fusion.globalContent,
never the page HTML.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urlsplit
from xml.etree import ElementTree

from news_politica.sources.http import Disallowed, ParseError, TransientError
from news_politica.sources.models import Article, Catalog, CatalogEntry, RawDoc
from news_politica.sources.text import article_id, html_to_text, join_paragraphs, to_art

START = date(2023, 12, 10)
CUTOFF = date(2026, 10, 1)  # exclusive: the dataset ends 2026-09-30 23:59 ART (add-dagster-assets)
SITEMAP_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
MARKER = "Fusion.globalContent="


@dataclass(frozen=True)
class ArcOutlet:
    medio: str
    site: str
    sitemap_url: Callable[[date], str]
    url_date: Callable[[str], date | None]
    is_live: Callable[[dict, str], bool]

    def is_politica(self, url):
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}" == self.site and parts.path.startswith("/politica/")


def sitemap_entries(xml):
    """(loc, lastmod) of every <url> in a sitemap."""
    root = ElementTree.fromstring(xml.encode())
    return [(u.findtext("s:loc", namespaces=SITEMAP_NS), u.findtext("s:lastmod", default="", namespaces=SITEMAP_NS))
            for u in root.findall("s:url", SITEMAP_NS)]


def story_json(page):
    """The Arc story JSON that the page embeds as Fusion.globalContent (ValueError if absent)."""
    start = page.index(MARKER) + len(MARKER)
    story, _ = json.JSONDecoder().raw_decode(page, start)
    return story


def build_catalog(client, outlet, start=START, end=None):
    """Política URLs of every daily sitemap from start to end (the scraping day), deduped by URL.

    A day whose sitemap still fails after retries goes to failed_days instead of aborting the crawl.
    """
    end = end or date.today()
    entries, seen, failed, dropped = [], set(), [], 0
    day = start
    while day <= end:
        try:
            response = client.get(outlet.sitemap_url(day))
            listed = sitemap_entries(response.text) if response.ok else None
        except (TransientError, ElementTree.ParseError):
            listed = None
        if listed is None:
            failed.append(day)
        for loc, lastmod in listed or []:
            if loc in seen or not outlet.is_politica(loc):
                continue
            seen.add(loc)
            url_date = outlet.url_date(loc)
            if url_date is None:
                dropped += 1
                continue
            entries.append(CatalogEntry(outlet.medio, loc, url_date, lastmod, day))
        day += timedelta(days=1)
    return Catalog(entries, failed, dropped)


def fetch_story(client, outlet, url):
    """The note's story JSON as a RawDoc, or a RawDoc with the reason it is gone or unusable."""
    try:
        response = client.get(url)
    except Disallowed:
        return RawDoc(outlet.medio, url, url, 0, client.now(), error="disallowed")

    def lost(error):
        return RawDoc(outlet.medio, url, response.final_url, response.status, response.fetched_at, error=error)

    if not response.ok:
        return lost(f"http_{response.status}")
    if not outlet.is_politica(response.final_url):
        return lost("redirected")
    try:
        story = story_json(response.text)
    except ValueError:
        return lost("no_story")
    if story.get("type") != "story":
        return lost("no_story")
    return RawDoc(outlet.medio, url, response.final_url, response.status, response.fetched_at,
                  json.dumps(story, ensure_ascii=False))


def block_paragraphs(block):
    """Plain-text paragraphs of a body block; lists nest their items as blocks."""
    if block.get("type") in ("text", "header"):
        return [html_to_text(block.get("content"))]
    if block.get("type") == "list":
        return [p for item in block.get("items", []) for p in block_paragraphs(item)]
    return []


def parse_story(raw, outlet):
    story = raw.load()
    canonical = story.get("canonical_url") or ""
    url = canonical if canonical.startswith("http") else outlet.site + canonical if canonical else ""
    titulo = html_to_text((story.get("headlines") or {}).get("basic"))
    if not (url and story.get("first_publish_date") and titulo):
        raise ParseError(f"{raw.url}: missing canonical_url, first_publish_date or headline")
    taxonomy = story.get("taxonomy") or {}
    return Article(
        id=article_id(url),
        medio=outlet.medio,
        url=url,
        fecha_publicacion=to_art(story["first_publish_date"]),
        titulo=titulo,
        bajada=html_to_text((story.get("subheadlines") or {}).get("basic")),
        cuerpo=join_paragraphs(p for block in story.get("content_elements", []) for p in block_paragraphs(block)),
        autor=", ".join(c["name"] for c in (story.get("credits") or {}).get("by", []) if c.get("name")),
        seccion=(taxonomy.get("primary_section") or {}).get("_id") or "",
        tags=[t["text"] for t in taxonomy.get("tags", []) if t.get("text")],
        fuente_externa="",
        es_en_vivo=outlet.is_live(story, url),
        fecha_scraping=raw.fetched_at,
    )
