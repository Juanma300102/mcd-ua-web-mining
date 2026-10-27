"""Build the sources/ test fixtures from the phase 2 cache (data/probe_cache/).

Fixtures keep the real structure of each response but cut every note text to
~20 words, so the repo never republishes a note body. Run once, while the cache
exists:

    uv run python tests/fixtures/sources/build_fixtures.py
"""

import hashlib
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[3]
CACHE = ROOT / "data/probe_cache"
OUT = Path(__file__).parent

MAX_WORDS = 20
MAX_CHARS = 180

ARC_PICKS = {
    "infobae": {
        "sitemap": "https://www.infobae.com/arc/outboundfeeds/sitemap/2023-12-10/",
        "stories": {
            "story_normal": "https://www.infobae.com/politica/2024/03/25/las-negociaciones-por-la-ley-bases-entran-en-su-tramo-final-guillermo-francos-recibio-a-jorge-macri-y-a-cristian-ritondo/",
            "story_live": "https://www.infobae.com/politica/2024/12/10/el-primer-aniversario-de-javier-milei-como-presidente-en-vivo-todas-las-declaraciones-y-las-actividades-programadas/",
        },
    },
    "lanacion": {
        "sitemap": "https://www.lanacion.com.ar/sitemap-articles-from2026-07-25T00:00:00Z-to2026-07-26T00:00:00Z.xml",
        "stories": {
            "story_normal": "https://www.lanacion.com.ar/politica/javier-milei-ira-al-congreso-este-domingo-para-presentar-el-presupuesto-2025-nid10092024/",
            "story_lists": "https://www.lanacion.com.ar/politica/hablo-milei-probablemente-me-den-el-nobel-de-economia-nid25062024/",
            "story_special": "https://www.lanacion.com.ar/politica/373-reformas-el-gobierno-es-el-mas-reformista-de-la-historia-argentina-nid10122025/",
        },
    },
}
MISIONESONLINE_PAGE = ("https://misionesonline.net/wp-json/wp/v2/posts?categories=7&after=2026-01-25T00:00:00"
                       "&before=2026-01-26T00:00:00&per_page=100&_embed=author,wp:term")

# Story keys the parser or the T4.4 EDA can read; the rest (related content, promo items) is dropped.
STORY_KEYS = ["_id", "type", "subtype", "canonical_url", "website_url", "first_publish_date", "display_date",
              "headlines", "subheadlines", "content_elements", "credits", "taxonomy", "content_restrictions", "label"]
MARKER = "Fusion.globalContent="


def cached(url):
    key = hashlib.sha1(url.encode()).hexdigest()
    folder = CACHE / url.split("/")[2]
    return json.loads((folder / f"{key}.json").read_text()), (folder / f"{key}.body").read_text()


def shorten(text, words=MAX_WORDS):
    cut = " ".join(text.split()[:words])
    return cut if len(cut) <= MAX_CHARS else cut[:MAX_CHARS].rsplit(" ", 1)[0]


def plain(markup):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup or ""))).strip()


def trim_block(block):
    kind = block.get("type")
    if kind in ("text", "header"):
        return {"_id": block.get("_id"), "type": kind, "content": shorten(plain(block.get("content")))}
    if kind == "list":
        return {"_id": block.get("_id"), "type": kind, "list_type": block.get("list_type"),
                "items": [trim_block(item) for item in block.get("items", [])]}
    if kind == "raw_html":
        return {"_id": block.get("_id"), "type": kind, "content": "<div>…</div>"}
    return {"_id": block.get("_id"), "type": kind}


def trim_story(story):
    story = {key: story[key] for key in STORY_KEYS if key in story}
    story["headlines"] = {"basic": (story.get("headlines") or {}).get("basic", "")}
    if "subheadlines" in story:
        story["subheadlines"] = {"basic": shorten((story["subheadlines"] or {}).get("basic", ""))}
    story["content_elements"] = [trim_block(b) for b in story.get("content_elements", [])]
    story["credits"] = {"by": [{"type": c.get("type"), "name": c.get("name")}
                               for c in (story.get("credits") or {}).get("by", [])]}
    taxonomy = story.get("taxonomy") or {}
    primary = taxonomy.get("primary_section") or {}
    story["taxonomy"] = {"primary_section": {"_id": primary.get("_id"), "name": primary.get("name")},
                         "tags": [{"slug": t.get("slug"), "text": t.get("text")} for t in taxonomy.get("tags", [])]}
    return story


def story_json(page):
    start = page.index(MARKER) + len(MARKER)
    story, end = json.JSONDecoder().raw_decode(page, start)
    return story, start, end


def page_fixture(page, story):
    """The real <script> around Fusion.globalContent, with the trimmed story and nothing after it."""
    _, start, _ = story_json(page)
    script = page.rindex("<script", 0, start)
    head = page[script:start]
    return f"<html><body>{head}{json.dumps(story, ensure_ascii=False)};</script></body></html>\n"


def sitemap_fixture(xml, keep_other=6, keep_politica=4):
    header = xml[:xml.index("<url>")]
    urls = re.findall(r"<url>.*?</url>", xml, re.S)
    politica = [u for u in urls if "/politica/" in u][:keep_politica]
    other = [u for u in urls if "/politica/" not in u][:keep_other]
    # Captions are free text; the parser never reads them.
    entries = [re.sub(r"<image:caption>.*?</image:caption>", "", u, flags=re.S) for u in other[:2] + politica + other[2:]]
    return header + "".join(entries) + "</urlset>\n"


def trim_post(post):
    body = plain(post["content"]["rendered"])
    paragraphs = [f"<p>{html.escape(shorten(body))}</p>"]
    source = re.search(r"Fuente\s*:.*", body[-300:], re.I)
    if source:
        paragraphs.append(f"<p>{html.escape(shorten(source.group(0), 12))}</p>")
    excerpt = plain(post["excerpt"]["rendered"])
    auto = excerpt.endswith("[…]")
    excerpt = shorten(excerpt.replace("[…]", ""), 15) + (" [&hellip;]" if auto else "")
    embedded = post.get("_embedded", {})
    return {
        "id": post["id"], "date": post["date"], "date_gmt": post["date_gmt"], "link": post["link"],
        "title": {"rendered": post["title"]["rendered"]},
        "content": {"rendered": "\n".join(paragraphs)},
        "excerpt": {"rendered": f"<p>{excerpt}</p>"},
        "categories": post["categories"], "tags": post["tags"],
        "_embedded": {
            "author": [{"name": a.get("name")} for a in embedded.get("author", [])],
            "wp:term": [[{"taxonomy": t.get("taxonomy"), "name": t.get("name")} for t in group]
                        for group in embedded.get("wp:term", [])],
        },
    }


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    print(f"{path.relative_to(ROOT)}  {len(text.encode()) // 1024} KB")


def main():
    for outlet, picks in ARC_PICKS.items():
        _, xml = cached(picks["sitemap"])
        write(OUT / outlet / "sitemap.xml", sitemap_fixture(xml))
        for name, url in picks["stories"].items():
            _, page = cached(url)
            story = trim_story(story_json(page)[0])
            write(OUT / outlet / f"{name}.json", json.dumps(story, ensure_ascii=False, indent=1) + "\n")
            if name == "story_normal":
                write(OUT / outlet / "page.html", page_fixture(page, story))
    info, body = cached(MISIONESONLINE_PAGE)
    posts = [trim_post(p) for p in json.loads(body)]
    write(OUT / "misionesonline" / "posts_page.json", json.dumps(posts, ensure_ascii=False, indent=1) + "\n")
    headers = {k: v for k, v in info["headers"].items() if k.lower().startswith("x-wp")}
    write(OUT / "misionesonline" / "posts_page.headers.json", json.dumps(headers, indent=1) + "\n")


if __name__ == "__main__":
    main()
