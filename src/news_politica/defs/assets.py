"""Phase 4 assets: Arc catalogs, monthly raw documents per outlet and the unified dataset."""

from contextlib import contextmanager
from dataclasses import asdict, fields
from datetime import date, datetime, timedelta

import dagster as dg
import pandas as pd

from news_politica.sources import check_losses, parse
from news_politica.sources.arc import CUTOFF, START, build_catalog, fetch_story
from news_politica.sources.http import Blocked, ParseError, PoliteClient, TooManyLosses
from news_politica.sources.infobae import INFOBAE
from news_politica.sources.lanacion import LANACION
from news_politica.sources.misionesonline import MEDIO as MISIONESONLINE
from news_politica.sources.misionesonline import fetch_month
from news_politica.sources.models import Article, Catalog, CatalogEntry, RawDoc
from news_politica.sources.text import ART, article_id

# Cut-off 2026-09-30 23:59 ART (add-dagster-assets): October 2026 is not complete before the delivery.
MONTHS = dg.MonthlyPartitionsDefinition(start_date="2023-12-01", end_date="2026-10-01")
PERIOD_START = datetime(START.year, START.month, START.day, tzinfo=ART)
PERIOD_END = datetime(CUTOFF.year, CUTOFF.month, CUTOFF.day, tzinfo=ART)
RETRY = dg.RetryPolicy(max_retries=2, delay=300)
# Proof of concept: Arc notes fetched per month, chosen by URL hash so a re-run picks the same ones
# (~35 min per outlet instead of ~14 h). None fetches every note. MisionesOnline is always complete.
SAMPLE_PER_MONTH = 30
# Proof of concept: the catalogs read these sitemap days of each month (~70 sitemaps, not ~1,050).
# Two days list ~50 Política URLs per month, enough for the sample. None reads every day.
SITEMAP_DAYS = (5, 20)
# Progress lines are logged every LOG_EVERY sitemaps or notes, to keep the run log short.
LOG_EVERY = 10


def sampled_catalog(client, outlet, end=None, log=None):
    """build_catalog over SITEMAP_DAYS of every month from START to end, merged and deduped by URL."""
    end = end or date.today()
    if SITEMAP_DAYS is None:
        return build_catalog(client, outlet, end=end)
    days = [START + timedelta(days=n) for n in range((end - START).days + 1)]
    sitemap_days = [d for d in days if d.day in SITEMAP_DAYS]
    entries, failed, dropped, seen = [], [], 0, set()
    for done, day in enumerate(sitemap_days, start=1):
        part = build_catalog(client, outlet, start=day, end=day)
        entries += [e for e in part.entries if e.url not in seen]
        seen.update(e.url for e in part.entries)
        failed += part.failed_days
        dropped += part.dropped
        if log and (done % LOG_EVERY == 0 or done == len(sitemap_days)):
            log.info(f"{outlet.medio}: {done}/{len(sitemap_days)} sitemaps read (up to {day}), {len(entries)} entries")
    return Catalog(entries, failed, dropped)


def to_frame(rows, cls):
    return pd.DataFrame([asdict(row) for row in rows], columns=[f.name for f in fields(cls)])


def raw_docs(frame):
    # Missing strings come back from Parquet as NaN; RawDoc expects None.
    frame = frame.astype(object).where(frame.notna(), None)
    return [RawDoc(**row) for row in frame.to_dict("records")]


def month_bounds(partition_key):
    first = date.fromisoformat(partition_key)
    return first, date(first.year + first.month // 12, first.month % 12 + 1, 1)


@contextmanager
def no_retry_when_blocked():
    """A challenge or a layout change does not go away by retrying: fail without the RetryPolicy."""
    try:
        yield
    except (Blocked, TooManyLosses) as error:
        raise dg.Failure(f"{type(error).__name__}: {error}", allow_retries=False) from error


def checked(context, docs, **metadata):
    with no_retry_when_blocked():
        losses = check_losses(docs)
    context.add_output_metadata({**metadata, "notes": len(docs), "losses": losses})
    context.log.info(f"{context.partition_key}: {len(docs)} notes stored, {losses} lost")
    return to_frame(docs, RawDoc)


def arc_assets(outlet):
    @dg.asset(name=f"catalogo_{outlet.medio}", pool=outlet.medio, retry_policy=RETRY)
    def catalog(context, client: dg.ResourceParam[PoliteClient]) -> pd.DataFrame:
        """Política URLs of the SITEMAP_DAYS sitemaps of each month from 2023-12-10 to the scraping day."""
        context.log.info(f"{outlet.medio}: reading sitemaps from {START} to today (days {SITEMAP_DAYS})")
        with no_retry_when_blocked():
            result = sampled_catalog(client, outlet, log=context.log)
        context.log.info(f"{outlet.medio}: catalog has {len(result.entries)} entries, "
                         f"{len(result.failed_days)} failed days, {result.dropped} dropped")
        context.add_output_metadata({
            "entries": len(result.entries),
            "failed_days": ", ".join(str(day) for day in result.failed_days) or "none",
            "dropped": result.dropped,
        })
        return to_frame(result.entries, CatalogEntry)

    @dg.asset(name=f"raw_{outlet.medio}", ins={"catalog": dg.AssetIn(f"catalogo_{outlet.medio}")},
              partitions_def=MONTHS, backfill_policy=dg.BackfillPolicy.multi_run(1),
              pool=outlet.medio, retry_policy=RETRY)
    def raw(context, client: dg.ResourceParam[PoliteClient], catalog: pd.DataFrame) -> pd.DataFrame:
        """Story JSON of every catalog note whose URL date falls in the month."""
        first, following = month_bounds(context.partition_key)
        listed = [url for url, day in zip(catalog["url"], catalog["url_date"]) if first <= day < following]
        urls = sorted(listed, key=article_id)[:SAMPLE_PER_MONTH]
        context.log.info(f"{outlet.medio} {context.partition_key}: fetching {len(urls)} of {len(listed)} listed notes")
        docs = []
        with no_retry_when_blocked():
            for done, url in enumerate(urls, start=1):
                docs.append(fetch_story(client, outlet, url))
                if done % LOG_EVERY == 0 and done < len(urls):
                    context.log.info(f"{outlet.medio} {context.partition_key}: {done}/{len(urls)} notes fetched")
        return checked(context, docs, listed=len(listed))

    return catalog, raw


catalogo_infobae, raw_infobae = arc_assets(INFOBAE)
catalogo_lanacion, raw_lanacion = arc_assets(LANACION)


@dg.asset(partitions_def=MONTHS, backfill_policy=dg.BackfillPolicy.multi_run(1),
          pool=MISIONESONLINE, retry_policy=RETRY)
def raw_misionesonline(context, client: dg.ResourceParam[PoliteClient]) -> pd.DataFrame:
    """Every Política post of the month from the WordPress REST API."""
    context.log.info(f"{MISIONESONLINE} {context.partition_key}: fetching the month's posts")
    with no_retry_when_blocked():
        docs = fetch_month(client, date.fromisoformat(context.partition_key))
    return checked(context, docs)


# Missing months are skipped, so the dataset can be built from a partial backfill.
RAW_INPUT = {"allow_missing_partitions": True}


@dg.asset(ins={name: dg.AssetIn(metadata=RAW_INPUT) for name in ("raw_infobae", "raw_lanacion", "raw_misionesonline")})
def noticias_politica(context, raw_infobae: dict, raw_lanacion: dict, raw_misionesonline: dict) -> pd.DataFrame:
    """The three outlets in the dataset schema, 2023-12-10 to the cut-off, one row per URL."""
    articles, parse_errors = [], 0
    for name, months in (("infobae", raw_infobae), ("lanacion", raw_lanacion), ("misionesonline", raw_misionesonline)):
        context.log.info(f"{name}: parsing {len(months)} months")
        for frame in months.values():
            for doc in raw_docs(frame):
                if doc.error:
                    continue
                try:
                    articles.append(parse(doc))
                except ParseError:
                    parse_errors += 1
    frame = to_frame(articles, Article)
    in_period = (frame["fecha_publicacion"] >= PERIOD_START) & (frame["fecha_publicacion"] < PERIOD_END)
    frame = frame[in_period].drop_duplicates("url").reset_index(drop=True)
    context.log.info(f"{len(frame)} rows ({len(articles)} parsed, {parse_errors} parse errors)")
    context.add_output_metadata({
        "rows": len(frame),
        "rows_per_medio": dg.MetadataValue.json(frame["medio"].value_counts().to_dict()),
        "parse_errors": parse_errors,
    })
    return frame
