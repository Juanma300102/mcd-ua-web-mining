"""Plain text, ids and Argentina time for parsed articles."""

import hashlib
import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

# Argentina has had no daylight saving time since 2009.
ART = timezone(timedelta(hours=-3), "ART")
_SPACES = re.compile(r"\s+")
_BLOCK_END = re.compile(r"</p>|<br\s*/?>|</h[1-6]>|</li>|</blockquote>", re.IGNORECASE)


def html_to_text(markup):
    if not markup:
        return ""
    if "<" in markup or "&" in markup:
        markup = BeautifulSoup(markup, "lxml").get_text(" ")
    return _SPACES.sub(" ", markup).strip()


def join_paragraphs(paragraphs):
    return "\n\n".join(p for p in paragraphs if p)


def html_to_paragraphs(markup):
    """Plain text that keeps paragraph breaks as a blank line."""
    return join_paragraphs(html_to_text(chunk) for chunk in _BLOCK_END.split(markup or ""))


def article_id(url):
    return hashlib.sha1(url.encode()).hexdigest()


def to_art(value):
    """An ISO 8601 timestamp in UTC (naive values are UTC too) as a datetime at UTC-3."""
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(ART)
