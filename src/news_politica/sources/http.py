"""Polite HTTP client shared by every outlet, and the errors the clients raise.

Only robots.txt-allowed URLs, an identifiable User-Agent, at least 2 s between
requests to the same host (retries included), bounded retries for transient
failures, and no anti-bot bypass: a challenge blocks the host for the rest of
the client's life. Based on notebooks/probe.py, without its cache.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

USER_AGENT = "news-politica/0.1 (+https://github.com/Juanma300102/mcd-ua-web-mining)"
MIN_INTERVAL = 2.0
TIMEOUT = 30
BACKOFF = (2, 8, 32)
MAX_RETRY_AFTER = 300
_NETWORK_ERRORS = (requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError)


class SourceError(Exception):
    """Base class for every error raised by sources/."""


class TransientError(SourceError):
    """Retries ran out on a timeout, connection error, 5xx or 429. The caller may retry later."""


class Blocked(SourceError):
    """The host answered with an anti-bot challenge or an unreadable robots.txt. Never retried."""

    def __init__(self, host, response=None):
        super().__init__(host)
        self.host = host
        self.response = response


class Disallowed(SourceError):
    """robots.txt disallows the URL; nothing was sent."""


class TooManyLosses(SourceError):
    """Too many notes of a partition came back gone or unusable: likely a layout change."""


class ParseError(SourceError):
    """A raw document lacks a required field or is unreadable."""


@dataclass(frozen=True)
class Response:
    url: str
    final_url: str
    status: int
    headers: dict
    text: str
    fetched_at: datetime

    @property
    def ok(self):
        return 200 <= self.status < 300

    def header(self, name):
        return {k.lower(): v for k, v in self.headers.items()}.get(name.lower())


def is_challenge(response):
    if response.status != 403:
        return False
    return response.header("cf-mitigated") == "challenge" or "<title>Just a moment...</title>" in response.text


def retry_after(response, now):
    """Seconds the server asked to wait, from a Retry-After header in seconds or as an HTTP date."""
    value = response.header("retry-after")
    if not value:
        return 0
    if value.strip().isdigit():
        return int(value)
    try:
        return max(0, (parsedate_to_datetime(value) - now).total_seconds())
    except (TypeError, ValueError):
        return 0


class PoliteClient:
    def __init__(self, session=None, clock=time.monotonic, sleep=time.sleep, min_interval=MIN_INTERVAL,
                 now=lambda: datetime.now(timezone.utc)):
        self.session = session or requests.Session()
        self.clock = clock
        self.sleep = sleep
        self.min_interval = min_interval
        self.now = now
        self._robots = {}
        self._blocked = {}
        self._last_request = {}

    def get(self, url):
        host = urlsplit(url).netloc
        self._check_robots(url, host)
        return self._fetch(url, host)

    def _check_robots(self, url, host):
        if host in self._blocked:
            raise Blocked(host, self._blocked[host])
        if host not in self._robots:
            response = self._fetch(f"{urlsplit(url).scheme}://{host}/robots.txt", host)
            if not response.ok:
                self._blocked[host] = response
                raise Blocked(host, response)
            parser = RobotFileParser()
            parser.parse(response.text.splitlines())
            self._robots[host] = parser
        if not self._robots[host].can_fetch(USER_AGENT, url):
            raise Disallowed(url)

    def _fetch(self, url, host):
        for attempt, backoff in enumerate((*BACKOFF, None), start=1):
            if host in self._blocked:
                raise Blocked(host, self._blocked[host])
            self._wait(host)
            try:
                raw = self.session.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
            except _NETWORK_ERRORS as error:
                failure, wait = repr(error), backoff
            else:
                response = Response(url, raw.url or url, raw.status_code, dict(raw.headers), raw.text, self.now())
                if is_challenge(response):
                    self._blocked[host] = response
                    raise Blocked(host, response)
                if response.status != 429 and response.status < 500:
                    return response
                failure = f"HTTP {response.status}"
                wait = backoff and max(backoff, min(retry_after(response, self.now()), MAX_RETRY_AFTER))
            if backoff is None:
                raise TransientError(f"{url}: {failure} after {attempt} attempts")
            self.sleep(wait)

    def _wait(self, host):
        wait = self._last_request.get(host, float("-inf")) + self.min_interval - self.clock()
        if wait > 0:
            self.sleep(wait)
        self._last_request[host] = self.clock()
