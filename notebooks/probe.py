"""Polite HTTP helper for the phase 2 exploration notebooks.

Only robots.txt-allowed paths, an identifiable User-Agent, at least 2 s between
requests to the same host, and no anti-bot bypass: a challenge marks the host as
blocked and nothing else is sent to it. Responses are cached under
data/probe_cache/ so notebooks can be re-run; PROBE_OFFLINE=1 serves everything
from the cache and fails on a miss instead of touching the network.

Throwaway: phase 3 writes the real client in src/news_politica/sources/.
"""

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

USER_AGENT = "news-politica-research/0.1 (+https://github.com/Juanma300102/mcd-ua-web-mining)"
MIN_INTERVAL = 2.0
CACHE_DIR = Path(__file__).parents[1] / "data/probe_cache"


class Disallowed(Exception):
    """The URL is disallowed by the host's robots.txt; nothing was sent."""


class Blocked(Exception):
    """The host answered with a challenge or an unreadable robots.txt; nothing else is sent to it."""

    def __init__(self, host, response=None):
        super().__init__(host)
        self.host = host
        self.response = response


class CacheMiss(Exception):
    """Offline mode needed a response that is not in the cache."""


@dataclass
class Response:
    url: str
    status: int
    headers: dict
    text: str
    fetched_at: str
    from_cache: bool = False

    @property
    def ok(self):
        return 200 <= self.status < 300


def is_challenge(response):
    if response.status != 403:
        return False
    mitigated = {k.lower(): v for k, v in response.headers.items()}.get("cf-mitigated", "")
    return mitigated == "challenge" or "<title>Just a moment...</title>" in response.text


def story_json(html):
    """The Arc story JSON that Arc XP pages embed as Fusion.globalContent."""
    marker = "Fusion.globalContent="
    start = html.index(marker) + len(marker)
    story, _ = json.JSONDecoder().raw_decode(html, start)
    return story


class Probe:
    def __init__(self, cache_dir=CACHE_DIR, session=None, clock=time.monotonic, sleep=time.sleep,
                 min_interval=MIN_INTERVAL, offline=None):
        self.cache_dir = Path(cache_dir)
        self.session = session or requests.Session()
        self.clock = clock
        self.sleep = sleep
        self.min_interval = min_interval
        self.offline = os.environ.get("PROBE_OFFLINE") == "1" if offline is None else offline
        self.network_requests = 0
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
            parts = urlsplit(url)
            response = self._fetch(f"{parts.scheme}://{host}/robots.txt", host)
            if not response.ok:
                self._blocked[host] = response
                raise Blocked(host, response)
            parser = RobotFileParser()
            parser.parse(response.text.splitlines())
            self._robots[host] = parser
        if not self._robots[host].can_fetch(USER_AGENT, url):
            raise Disallowed(url)

    def _fetch(self, url, host):
        if host in self._blocked:
            raise Blocked(host, self._blocked[host])
        response = self._read_cache(url)
        if response is None or not (response.ok or self.offline):
            if self.offline:
                raise CacheMiss(url)
            response = self._request(url, host)
        if is_challenge(response):
            self._blocked[host] = response
        return response

    def _request(self, url, host):
        wait = self._last_request.get(host, float("-inf")) + self.min_interval - self.clock()
        if wait > 0:
            self.sleep(wait)
        self._last_request[host] = self.clock()
        raw = self.session.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        self.network_requests += 1
        response = Response(url, raw.status_code, dict(raw.headers), raw.text,
                            datetime.now(timezone.utc).isoformat(timespec="seconds"))
        # Failures are recorded for offline replay, but online get() requests them again.
        self._write_cache(response)
        return response

    def _paths(self, url):
        key = hashlib.sha1(url.encode()).hexdigest()
        folder = self.cache_dir / urlsplit(url).netloc
        return folder / f"{key}.body", folder / f"{key}.json"

    def _read_cache(self, url):
        body, meta = self._paths(url)
        if not meta.exists():
            return None
        info = json.loads(meta.read_text())
        text = body.read_text() if body.exists() else ""
        return Response(url, info["status"], info["headers"], text, info["fetched_at"], from_cache=True)

    def _write_cache(self, response):
        body, meta = self._paths(response.url)
        body.parent.mkdir(parents=True, exist_ok=True)
        body.write_text(response.text)
        meta.write_text(json.dumps({"url": response.url, "status": response.status,
                                    "headers": response.headers, "fetched_at": response.fetched_at}))
