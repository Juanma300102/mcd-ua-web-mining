from pathlib import Path

import pytest

FIXTURES = Path(__file__).parents[1] / "fixtures/sources"
ROBOTS = "User-agent: *\nDisallow: /pf/api/\n"


class FakeRaw:
    def __init__(self, status, text="", headers=None, url=None):
        self.status_code = status
        self.text = text
        self.headers = headers or {}
        self.url = url


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeSession:
    """Serves routes by URL. A route is a FakeRaw, an exception, or a list of them served in order
    (the last one repeats). Every robots.txt answers ROBOTS unless a route overrides it; any other
    unknown URL fails the test."""

    def __init__(self, clock, routes=None):
        self.clock = clock
        self.routes = dict(routes or {})
        self.calls = []

    def get(self, url, headers, timeout, allow_redirects=True):
        self.calls.append((url, self.clock.now, headers["User-Agent"]))
        route = self.routes.get(url)
        if route is None and url.endswith("/robots.txt"):
            route = FakeRaw(200, ROBOTS)
        if route is None:
            raise AssertionError(f"unexpected request: {url}")
        if isinstance(route, list):
            route = route.pop(0) if len(route) > 1 else route[0]
        if isinstance(route, Exception):
            raise route
        if route.url is None:
            return FakeRaw(route.status_code, route.text, route.headers, url)
        return route

    def requested(self, url):
        return [call for call in self.calls if call[0] == url]


def fixture_text(*parts):
    return FIXTURES.joinpath(*parts).read_text()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def session(clock):
    return FakeSession(clock)


@pytest.fixture
def client(session, clock):
    from news_politica.sources.http import PoliteClient

    return PoliteClient(session=session, clock=clock, sleep=clock.sleep)
