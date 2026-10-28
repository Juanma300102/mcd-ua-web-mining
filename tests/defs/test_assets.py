import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import dagster as dg
import pytest
import yaml
from upath import UPath

from news_politica.defs import assets
from news_politica.defs.assets import (
    catalogo_infobae, catalogo_lanacion, no_retry_when_blocked, noticias_politica, raw_infobae, raw_lanacion,
    raw_misionesonline, to_frame,
)
from news_politica.defs.io import ParquetIOManager
from news_politica.sources.arc import build_catalog
from news_politica.sources.http import TransientError
from news_politica.sources.infobae import INFOBAE
from news_politica.sources.misionesonline import fetch_month, month_url
from news_politica.sources.models import CatalogEntry, RawDoc

from ..sources.conftest import FakeRaw, fixture_text
from .conftest import UPSTREAM, info_logs, metadata, store

DAGSTER_YAML = Path(__file__).parents[2] / "src/news_politica/dagster_home/dagster.yaml"
FETCHED = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
MARCH = "2024-03-01"
CHALLENGE = FakeRaw(403, "<title>Just a moment...</title>", {"cf-mitigated": "challenge"})


def note_url(slug):
    return f"{INFOBAE.site}/politica/2024/03/01/{slug}/"


def run(tmp_path, client, selection, partition_key=None, instance=None):
    resources = {"io_manager": ParquetIOManager(base_path=UPath(tmp_path)), "client": client}
    return dg.materialize(UPSTREAM, selection=selection, resources=resources, partition_key=partition_key,
                          instance=instance, raise_on_error=False)


def store_catalog(tmp_path, days):
    entries = [CatalogEntry("infobae", note_url(f"nota-{day}"), day, "", day) for day in days]
    store(tmp_path, "catalogo_infobae", to_frame(entries, CatalogEntry))



# Instance and definitions


def test_pools_limit_one_run_per_outlet():
    pools = yaml.safe_load(DAGSTER_YAML.read_text())["concurrency"]["pools"]
    assert pools == {"default_limit": 1, "granularity": "run"}


def test_assets_carry_their_outlet_pool():
    pools = {a.key.to_user_string(): a.op.pool for a in UPSTREAM}
    assert pools == {
        "catalogo_infobae": "infobae", "raw_infobae": "infobae",
        "catalogo_lanacion": "lanacion", "raw_lanacion": "lanacion",
        "raw_misionesonline": "misionesonline", "noticias_politica": None,
    }


def test_raw_partitions_end_at_the_cut_off():
    keys = raw_infobae.partitions_def.get_partition_keys()
    assert (keys[0], keys[-1], len(keys)) == ("2023-12-01", "2026-09-01", 34)


# Catalog


def test_catalog_reports_failed_days(tmp_path, client, session, monkeypatch):
    day = date(2023, 12, 10)
    session.routes[INFOBAE.sitemap_url(day)] = FakeRaw(200, fixture_text("infobae", "sitemap.xml"))
    session.routes[INFOBAE.sitemap_url(day + timedelta(days=1))] = FakeRaw(500)
    monkeypatch.setattr(assets, "sampled_catalog",
                        lambda client, outlet, log=None: build_catalog(client, outlet, start=day, end=day + timedelta(days=1)))
    result = run(tmp_path, client, [catalogo_infobae])
    assert result.success
    assert metadata(result, "catalogo_infobae") == {"entries": 4, "failed_days": "2023-12-11", "dropped": 0}


def test_catalog_reads_only_the_sitemap_days(client, session):
    for day in (date(2023, 12, 20), date(2024, 1, 5), date(2024, 1, 20)):
        session.routes[INFOBAE.sitemap_url(day)] = FakeRaw(200, fixture_text("infobae", "sitemap.xml"))
    catalog = assets.sampled_catalog(client, INFOBAE, end=date(2024, 1, 31))
    sitemaps = [url for url, *_ in session.calls if "sitemap" in url]
    assert sitemaps == [INFOBAE.sitemap_url(d) for d in (date(2023, 12, 20), date(2024, 1, 5), date(2024, 1, 20))]
    assert len(catalog.entries) == 4 and catalog.failed_days == []


# Raw partitions


def test_arc_month_fetches_only_its_catalog_entries(tmp_path, client, session):
    store_catalog(tmp_path, [date(2024, 2, 29), date(2024, 3, 1), date(2024, 3, 31), date(2019, 5, 1)])
    page = FakeRaw(200, fixture_text("infobae", "page.html"))
    for day in (date(2024, 3, 1), date(2024, 3, 31)):
        session.routes[note_url(f"nota-{day}")] = page
    result = run(tmp_path, client, [raw_infobae], MARCH)
    assert result.success
    assert metadata(result, "raw_infobae") == {"listed": 2, "notes": 2, "losses": 0}
    assert len(session.requested(note_url("nota-2024-02-29"))) == 0
    assert len(session.requested(note_url("nota-2019-05-01"))) == 0


def test_arc_month_fetches_a_stable_sample(tmp_path, client, session, monkeypatch):
    monkeypatch.setattr(assets, "SAMPLE_PER_MONTH", 2)
    days = [date(2024, 3, day) for day in (1, 2, 3, 4)]
    store_catalog(tmp_path, days)
    page = FakeRaw(200, fixture_text("infobae", "page.html"))
    for day in days:
        session.routes[note_url(f"nota-{day}")] = page
    result = run(tmp_path, client, [raw_infobae], MARCH)
    assert metadata(result, "raw_infobae") == {"listed": 4, "notes": 2, "losses": 0}
    fetched = {url for url, *_ in session.calls if "nota-" in url}
    assert fetched == set(sorted((note_url(f"nota-{d}") for d in days), key=assets.article_id)[:2])


def test_too_many_losses_fail_the_month(tmp_path, client, session):
    store_catalog(tmp_path, [date(2024, 3, 1)])
    session.routes[note_url("nota-2024-03-01")] = FakeRaw(404)
    result = run(tmp_path, client, [raw_infobae], MARCH)
    assert not result.success
    assert not (tmp_path / "raw_infobae" / f"{MARCH}.parquet").exists()


def test_blocked_host_fails_without_retry(tmp_path, client, session):
    # A retry would also sleep the policy's 300 s; the URL must be requested once.
    store_catalog(tmp_path, [date(2024, 3, 1), date(2024, 3, 2)])
    for day in (1, 2):
        session.routes[note_url(f"nota-2024-03-0{day}")] = CHALLENGE
    result = run(tmp_path, client, [raw_infobae], MARCH)
    assert not result.success
    # The first note met the challenge; the host is blocked, so the second is never sent.
    assert len([url for url, *_ in session.calls if "nota-" in url]) == 1


def test_transient_failures_stay_retryable():
    with pytest.raises(TransientError):
        with no_retry_when_blocked():
            raise TransientError("timeout")
    assert raw_infobae.op.retry_policy.max_retries == 2


def test_misionesonline_month(tmp_path, client, session):
    session.routes[month_url(date(2026, 1, 1), 1)] = FakeRaw(
        200, fixture_text("misionesonline", "posts_page.json"), {"X-WP-TotalPages": "1"})
    result = run(tmp_path, client, [raw_misionesonline], "2026-01-01")
    assert result.success
    assert metadata(result, "raw_misionesonline") == {"notes": 4, "losses": 0}


# Progress logs


def test_arc_month_logs_its_progress(tmp_path, client, session):
    days = [date(2024, 3, day) for day in range(1, 26)]
    store_catalog(tmp_path, days)
    page = FakeRaw(200, fixture_text("infobae", "page.html"))
    for day in days:
        session.routes[note_url(f"nota-{day}")] = page
    with dg.DagsterInstance.ephemeral() as instance:
        result = run(tmp_path, client, [raw_infobae], MARCH, instance)
        assert result.success
        logs = info_logs(instance, result)
    [start, *progress, summary] = [m for m in logs if "infobae" in m or "notes stored" in m]
    assert "fetching 25 of 25 listed notes" in start
    assert [m.split()[-3] for m in progress] == ["10/25", "20/25"]
    assert f"{MARCH}: 25 notes stored, 0 lost" in summary
    assert not any("nota-" in m for m in logs)


def test_catalog_logs_start_progress_and_summary(tmp_path, client, session, monkeypatch):
    day = date(2023, 12, 10)
    session.routes[INFOBAE.sitemap_url(day)] = FakeRaw(200, fixture_text("infobae", "sitemap.xml"))
    monkeypatch.setattr(assets, "sampled_catalog",
                        lambda client, outlet, log=None: build_catalog(client, outlet, start=day, end=day))
    with dg.DagsterInstance.ephemeral() as instance:
        result = run(tmp_path, client, [catalogo_infobae], instance=instance)
        logs = info_logs(instance, result)
    assert "reading sitemaps" in logs[0]
    assert "catalog has 4 entries, 0 failed days, 0 dropped" in logs[-1]


def test_sampled_catalog_logs_every_ten_sitemaps_and_the_last(client, session, monkeypatch):
    monkeypatch.setattr(assets, "SITEMAP_DAYS", (5, 20))
    end = date(2024, 5, 31)  # 11 sitemap days: 2023-12-20 plus the 5th and 20th of five months
    for n in range((end - assets.START).days + 1):
        session.routes[INFOBAE.sitemap_url(assets.START + timedelta(days=n))] = FakeRaw(
            200, fixture_text("infobae", "sitemap.xml"))
    messages = []
    log = type("Log", (), {"info": staticmethod(messages.append)})
    assets.sampled_catalog(client, INFOBAE, end=end, log=log)
    assert [m.split()[1] for m in messages] == ["10/11", "11/11"]


# Unified dataset


def arc_doc(**changes):
    story = json.loads(fixture_text("infobae", "story_normal.json")) | changes
    url = INFOBAE.site + story["canonical_url"]
    return RawDoc("infobae", url, url, 200, FETCHED, json.dumps(story, ensure_ascii=False))


def test_noticias_politica_filters_dedupes_and_counts_errors(tmp_path, client, session):
    session.routes[month_url(date(2026, 1, 1), 1)] = FakeRaw(
        200, fixture_text("misionesonline", "posts_page.json"), {"X-WP-TotalPages": "1"})
    store(tmp_path, "raw_misionesonline", to_frame(fetch_month(client, date(2026, 1, 1)), RawDoc), "2026-01-01")
    normal = arc_doc()
    infobae = [
        normal,
        replace(normal),  # same URL twice
        arc_doc(canonical_url="/politica/2026/09/30/tarde/", first_publish_date="2026-10-01T03:30:00Z"),
        arc_doc(canonical_url="/politica/2024/03/25/sin-titulo/", headlines={}),
        RawDoc("infobae", note_url("borrada"), note_url("borrada"), 404, FETCHED, error="http_404"),
    ]
    store(tmp_path, "raw_infobae", to_frame(infobae, RawDoc), MARCH)

    result = run(tmp_path, client, [noticias_politica])
    assert result.success
    frame = result.output_for_node("noticias_politica")
    assert sorted(frame["medio"]) == ["infobae"] + ["misionesonline"] * 4
    assert frame["url"].is_unique and not frame["url"].str.contains("tarde").any()
    assert metadata(result, "noticias_politica") == {
        "rows": 5, "rows_per_medio": {"misionesonline": 4, "infobae": 1}, "parse_errors": 1}


def test_dataset_logs_its_summary(tmp_path, client, session):
    session.routes[month_url(date(2026, 1, 1), 1)] = FakeRaw(
        200, fixture_text("misionesonline", "posts_page.json"), {"X-WP-TotalPages": "1"})
    store(tmp_path, "raw_misionesonline", to_frame(fetch_month(client, date(2026, 1, 1)), RawDoc), "2026-01-01")
    with dg.DagsterInstance.ephemeral() as instance:
        result = run(tmp_path, client, [noticias_politica], instance=instance)
        assert result.success
        logs = info_logs(instance, result)
    assert any("misionesonline: parsing 1 months" in m for m in logs)
    assert any("4 rows (4 parsed, 0 parse errors)" in m for m in logs)
