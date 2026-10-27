"""Shared sampling and parsing for the Arc XP outlets (Infobae, La Nación).

Lists Política notes from daily sitemaps and reads each note's embedded story
JSON (Fusion.globalContent). All requests go through probe.Probe.
"""

import calendar
import html
import re
from datetime import date, timedelta
from xml.etree import ElementTree

import pandas as pd

from probe import story_json

START = date(2023, 12, 10)
SAMPLE_DAYS = (10, 25)
SITEMAP_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
LIVE_PATTERN = re.compile(r"en[ -]vivo|minuto[ -]a[ -]minuto", re.IGNORECASE)

# Dataset column -> where it comes from in the Arc story JSON (docs/def.md schema).
FIELD_SOURCES = {
    "id": "hash of canonical_url (computed)",
    "medio": "constant per outlet",
    "url": "canonical_url (relative, prefixed with the site)",
    "fecha_publicacion": "first_publish_date (UTC, converted to UTC-3)",
    "titulo": "headlines.basic",
    "bajada": "subheadlines.basic",
    "cuerpo": "content_elements of type text, header and list (HTML)",
    "autor": "credits.by[].name",
    "seccion": "taxonomy.primary_section._id",
    "tags": "taxonomy.tags[].text",
    "fecha_scraping": "none (set by the client)",
}


def sample_days(last_month, days=SAMPLE_DAYS, start=START):
    """Days 10 and 25 of every month from the start month to last_month (a date in that month)."""
    result = []
    year, month = start.year, start.month
    while (year, month) <= (last_month.year, last_month.month):
        result += [date(year, month, d) for d in days if date(year, month, d) >= start]
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def sitemap_entries(xml):
    root = ElementTree.fromstring(xml.encode())
    return [(u.findtext("s:loc", namespaces=SITEMAP_NS), u.findtext("s:lastmod", namespaces=SITEMAP_NS))
            for u in root.findall("s:url", SITEMAP_NS)]


def count_sitemaps(probe, days, sitemap_url, is_politica):
    """One row per day: sitemap status, total URLs and the Política URLs."""
    rows = []
    for day in days:
        response = probe.get(sitemap_url(day))
        entries = sitemap_entries(response.text) if response.ok else []
        politica = [loc for loc, _ in entries if is_politica(loc)]
        rows.append({"day": day, "status": response.status, "total_urls": len(entries),
                     "politica": len(politica), "politica_urls": politica})
    return pd.DataFrame(rows)


def monthly_estimate(counts, start=START):
    """Mean Política notes per sampled day × days in the month (from the start day in the first month)."""
    frame = counts.assign(month=pd.PeriodIndex(pd.to_datetime(counts["day"]), freq="M"))
    rows = []
    for month, group in frame.groupby("month"):
        days_in_month = calendar.monthrange(month.year, month.month)[1]
        if (month.year, month.month) == (start.year, start.month):
            days_in_month -= start.day - 1
        low, high = group["politica"].min(), group["politica"].max()
        rows.append({"month": str(month), "sampled": list(group["politica"]),
                     "estimated_notes": round(group["politica"].mean() * days_in_month),
                     "spread_over_2x": bool(low == 0 or high / low > 2)})
    return pd.DataFrame(rows)


def pick_notes(counts):
    """First and middle Política URL of every sampled sitemap."""
    picks = []
    for row in counts.itertuples():
        urls = row.politica_urls
        if urls:
            picks += [(row.day, url) for url in dict.fromkeys([urls[0], urls[len(urls) // 2]])]
    return picks


def text_of(markup):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup or ""))).strip()


def element_text(element):
    """Plain text of a body block; lists nest their items as blocks."""
    if element.get("type") in ("text", "header"):
        return text_of(element.get("content"))
    if element.get("type") == "list":
        return " ".join(element_text(item) for item in element.get("items", []))
    return ""


def read_note(probe, url):
    """Schema-relevant values from a note's story JSON, plus paywall and live-blog signals."""
    response = probe.get(url)
    if not response.ok:
        return {"url": url, "status": response.status}
    story = story_json(response.text)
    body = " ".join(filter(None, (element_text(e) for e in story.get("content_elements", []))))
    headline = (story.get("headlines") or {}).get("basic") or ""
    live = []
    if LIVE_PATTERN.search(url):
        live.append("url")
    if LIVE_PATTERN.search(headline):
        live.append("headline")
    return {
        "url": url,
        "status": response.status,
        "canonical_url": story.get("canonical_url"),
        "fecha_publicacion": story.get("first_publish_date"),
        "display_date": story.get("display_date"),
        "titulo": headline,
        "bajada": (story.get("subheadlines") or {}).get("basic") or "",
        "cuerpo_words": len(body.split()),
        "autor": [c.get("name") for c in (story.get("credits") or {}).get("by", []) if c.get("name")],
        "seccion": ((story.get("taxonomy") or {}).get("primary_section") or {}).get("_id"),
        "tags": [t.get("text") for t in (story.get("taxonomy") or {}).get("tags", []) if t.get("text")],
        "subtype": story.get("subtype"),
        "label": (story.get("label") or {}),
        "content_code": (story.get("content_restrictions") or {}).get("content_code"),
        "live_signals": live,
    }


def read_notes(probe, picks):
    return pd.DataFrame([{"sitemap_day": day, **read_note(probe, url)} for day, url in picks])


def field_presence(notes):
    """One row per dataset column: source path and share of sampled notes with a value."""
    ok = notes[notes["status"] == 200]
    present = {
        "url": ok["canonical_url"].notna(),
        "fecha_publicacion": ok["fecha_publicacion"].notna(),
        "titulo": ok["titulo"].str.len() > 0,
        "bajada": ok["bajada"].str.len() > 0,
        "cuerpo": ok["cuerpo_words"] > 0,
        "autor": ok["autor"].str.len() > 0,
        "seccion": ok["seccion"].notna(),
        "tags": ok["tags"].str.len() > 0,
    }
    present["id"] = present["url"]
    return pd.DataFrame([{"column": column, "source": source,
                          "present_share": round(present[column].mean(), 3) if column in present else None}
                         for column, source in FIELD_SOURCES.items()])


def url_day_offsets(counts, url_date):
    """Days between each Política URL's own date and the sitemap day it was listed in."""
    rows = []
    for row in counts.itertuples():
        for url in row.politica_urls:
            own = url_date(url)
            rows.append({"sitemap_day": row.day, "offset_days": (own - row.day).days if own else None})
    frame = pd.DataFrame(rows)
    return frame["offset_days"].value_counts(dropna=False).sort_index().rename("urls")


def neighbour_overlap(probe, days, sitemap_url, is_politica):
    """For each day, how many Política URLs also appear in the day before or after."""
    rows = []
    for day in days:
        listed = {}
        for offset in (-1, 0, 1):
            response = probe.get(sitemap_url(day + timedelta(days=offset)))
            listed[offset] = {loc for loc, _ in sitemap_entries(response.text) if is_politica(loc)} if response.ok else set()
        rows.append({"day": day, "politica": len(listed[0]),
                     "also_day_before": len(listed[0] & listed[-1]), "also_day_after": len(listed[0] & listed[1])})
    return pd.DataFrame(rows)
