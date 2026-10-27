"""Infobae (T3.3): daily sitemaps grouped by last modification, URLs dated /politica/YYYY/MM/DD/."""

import re
from datetime import date

from news_politica.sources.arc import ArcOutlet

SITE = "https://www.infobae.com"
_URL_DATE = re.compile(r"/politica/(\d{4})/(\d{2})/(\d{2})/")


def sitemap_url(day):
    return f"{SITE}/arc/outboundfeeds/sitemap/{day:%Y-%m-%d}/"


def url_date(url):
    match = _URL_DATE.search(url)
    try:
        return date(*map(int, match.groups())) if match else None
    except ValueError:
        return None


def is_live(story, url):
    return story.get("subtype") == "live-blogging"


INFOBAE = ArcOutlet("infobae", SITE, sitemap_url, url_date, is_live)
