"""MisionesOnline: Política posts from the WordPress REST API (T3.2).

The API filters by publish date in site time (UTC-3), so a month is one query
with no catalog, and every post already carries its body.
"""

import json
import re
from datetime import date

from news_politica.sources.http import ParseError, SourceError
from news_politica.sources.models import Article, RawDoc
from news_politica.sources.text import article_id, html_to_text, to_art

MEDIO = "misionesonline"
API = "https://misionesonline.net/wp-json/wp/v2/posts"
POLITICA = 7
PER_PAGE = 100

# Rewrites of national outlets close with "Fuente: X" (decision-fuentes.md, "Notas de agencia").
SOURCE = re.compile(r"Fuente\s*:\s*([^.\n]{2,40})", re.IGNORECASE)
# Drop what follows the outlet name: "INFOBAE 👉 MANTENETE…", "ÁMBITO LAS ACCIONES…", "INFOBAE LEE TAMBIÉN…".
TRAILER = re.compile(r"\s*👉.*|\s+(?:LEE TAMBIÉN:?|EL|LAS|LOS)\s.*")
# WordPress builds the excerpt from the body when none is written by hand.
AUTO_EXCERPT_PREFIX = 60


def month_url(month, page):
    first = month.replace(day=1)
    following = date(first.year + first.month // 12, first.month % 12 + 1, 1)
    return (f"{API}?categories={POLITICA}&after={first:%Y-%m-%d}T00:00:00&before={following:%Y-%m-%d}T00:00:00"
            f"&per_page={PER_PAGE}&_embed=author,wp:term&page={page}")


def fetch_month(client, month):
    """One RawDoc per Política post published in the month of `month` (site time)."""
    docs, page, pages = [], 1, 1
    while page <= pages:
        response = client.get(month_url(month, page))
        if not response.ok:
            raise SourceError(f"{response.url}: HTTP {response.status}")
        pages = int(response.header("x-wp-totalpages") or 0)
        for post in json.loads(response.text):
            post.pop("_links", None)
            docs.append(RawDoc(MEDIO, post["link"], post["link"], response.status, response.fetched_at,
                               json.dumps(post, ensure_ascii=False)))
        page += 1
    return docs


def _terms(post, taxonomy):
    groups = post.get("_embedded", {}).get("wp:term", [])
    return [t["name"] for group in groups for t in group if t.get("taxonomy") == taxonomy and t.get("name")]


def _bajada(excerpt, body):
    excerpt = excerpt.replace("[…]", "").strip()
    return "" if not excerpt or body.startswith(excerpt[:AUTO_EXCERPT_PREFIX]) else excerpt


def _fuente_externa(body):
    match = SOURCE.search(body[-300:])
    return TRAILER.sub("", match.group(1).strip().upper()).strip() if match else ""


def parse_post(raw):
    post = raw.load()
    url = post.get("link")
    titulo = html_to_text((post.get("title") or {}).get("rendered"))
    if not (url and post.get("date_gmt") and titulo):
        raise ParseError(f"{raw.url}: missing link, date_gmt or title")
    cuerpo = html_to_text((post.get("content") or {}).get("rendered"))
    return Article(
        id=article_id(url),
        medio=MEDIO,
        url=url,
        fecha_publicacion=to_art(post["date_gmt"]),
        titulo=titulo,
        bajada=_bajada(html_to_text((post.get("excerpt") or {}).get("rendered")), cuerpo),
        cuerpo=cuerpo,
        autor=", ".join(a["name"] for a in post.get("_embedded", {}).get("author", []) if a.get("name")),
        seccion=", ".join(_terms(post, "category")),
        tags=_terms(post, "post_tag"),
        fuente_externa=_fuente_externa(cuerpo),
        es_en_vivo=False,
        fecha_scraping=raw.fetched_at,
    )
