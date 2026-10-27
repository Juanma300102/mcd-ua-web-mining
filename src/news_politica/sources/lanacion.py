"""La Nación (T3.4): daily sitemaps grouped by display_date in UTC, URLs dated -nidDDMMYYYY."""

import re
from datetime import date, timedelta

from news_politica.sources.arc import ArcOutlet

SITE = "https://www.lanacion.com.ar"
_URL_DATE = re.compile(r"-nid(\d{2})(\d{2})(\d{4})/?$")
_LIVE = re.compile(r"en[ -]vivo|minuto[ -]a[ -]minuto", re.IGNORECASE)


def sitemap_url(day):
    return (f"{SITE}/sitemap-articles-from{day:%Y-%m-%d}T00:00:00Z"
            f"-to{day + timedelta(days=1):%Y-%m-%d}T00:00:00Z.xml")


def url_date(url):
    match = _URL_DATE.search(url)
    if not match:
        return None
    day, month, year = map(int, match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def is_live(story, url):
    headline = (story.get("headlines") or {}).get("basic") or ""
    return bool(_LIVE.search(url) or _LIVE.search(headline))


LANACION = ArcOutlet("lanacion", SITE, sitemap_url, url_date, is_live)
