import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("probe", Path(__file__).parents[1] / "notebooks/probe.py")
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

ROBOTS = "User-agent: *\nDisallow: /pf/api/\n"
CHALLENGE = "<!DOCTYPE html><html><head><title>Just a moment...</title></head></html>"


class FakeRaw:
    def __init__(self, status, text, headers=None):
        self.status_code = status
        self.text = text
        self.headers = headers or {}


class FakeSession:
    def __init__(self, routes, clock):
        self.routes = routes
        self.clock = clock
        self.calls = []

    def get(self, url, headers, timeout):
        self.calls.append((url, self.clock.now, headers["User-Agent"]))
        return self.routes.get(url, FakeRaw(200, "ok"))


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def make_probe(tmp_path, routes=None, offline=False):
    clock = FakeClock()
    session = FakeSession(routes or {"https://example.com/robots.txt": FakeRaw(200, ROBOTS)}, clock)
    instance = probe.Probe(cache_dir=tmp_path, session=session, clock=clock, sleep=clock.sleep, offline=offline)
    return instance, session


def test_disallowed_path_sends_nothing(tmp_path):
    instance, session = make_probe(tmp_path)

    with pytest.raises(probe.Disallowed):
        instance.get("https://example.com/pf/api/v3/content/fetch/x")

    assert [url for url, _, _ in session.calls] == ["https://example.com/robots.txt"]


def test_requests_send_project_user_agent_and_wait_between_them(tmp_path):
    instance, session = make_probe(tmp_path)

    instance.get("https://example.com/a")
    instance.get("https://example.com/b")

    times = [at for _, at, _ in session.calls]
    assert all(later - earlier >= probe.MIN_INTERVAL for earlier, later in zip(times, times[1:]))
    assert {agent for _, _, agent in session.calls} == {probe.USER_AGENT}


def test_cached_url_makes_no_request(tmp_path):
    first, _ = make_probe(tmp_path)
    first.get("https://example.com/a")

    second, session = make_probe(tmp_path)
    response = second.get("https://example.com/a")

    assert response.from_cache and response.text == "ok"
    assert session.calls == []


def test_failed_response_is_not_reused_as_success(tmp_path):
    routes = {"https://example.com/robots.txt": FakeRaw(200, ROBOTS), "https://example.com/a": FakeRaw(500, "error")}
    first, _ = make_probe(tmp_path, routes)
    assert first.get("https://example.com/a").status == 500

    second, session = make_probe(tmp_path)
    assert second.get("https://example.com/a").status == 200
    assert [url for url, _, _ in session.calls] == ["https://example.com/a"]


def test_challenge_blocks_the_host(tmp_path):
    routes = {
        "https://example.com/robots.txt": FakeRaw(200, ROBOTS),
        "https://example.com/a": FakeRaw(403, CHALLENGE, {"cf-mitigated": "challenge"}),
    }
    instance, session = make_probe(tmp_path, routes)

    assert probe.is_challenge(instance.get("https://example.com/a"))
    with pytest.raises(probe.Blocked):
        instance.get("https://example.com/b")
    assert len(session.calls) == 2


def test_unreadable_robots_blocks_the_host(tmp_path):
    routes = {"https://example.com/robots.txt": FakeRaw(403, CHALLENGE, {"cf-mitigated": "challenge"})}
    instance, session = make_probe(tmp_path, routes)

    with pytest.raises(probe.Blocked) as blocked:
        instance.get("https://example.com/wp-json/wp/v2/posts")
    with pytest.raises(probe.Blocked):
        instance.get("https://example.com/other")

    assert blocked.value.response.status == 403
    assert [url for url, _, _ in session.calls] == ["https://example.com/robots.txt"]


def test_offline_replays_cache_and_fails_on_miss(tmp_path):
    online, _ = make_probe(tmp_path)
    online.get("https://example.com/a")

    offline, session = make_probe(tmp_path, offline=True)
    assert offline.get("https://example.com/a").text == "ok"
    with pytest.raises(probe.CacheMiss):
        offline.get("https://example.com/b")
    assert session.calls == []


def test_story_json_reads_fusion_global_content():
    html = '<script>Fusion.globalContent={"headlines":{"basic":"T};x"}};Fusion.contentCache={};</script>'

    assert probe.story_json(html) == {"headlines": {"basic": "T};x"}}
