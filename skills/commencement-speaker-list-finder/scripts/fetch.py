"""Polite HTTP fetcher: User-Agent, robots, per-domain rate limit, retries."""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)


USER_AGENT = os.environ.get(
    "USER_AGENT",
    "commencement-speaker-list-finder/0.1 (contact: you@example.com)",
)
RATE_LIMIT_PER_DOMAIN_RPS = float(os.environ.get("RATE_LIMIT_PER_DOMAIN_RPS", "1.0"))
HTTP_TIMEOUT_SECONDS = int(os.environ.get("HTTP_TIMEOUT_SECONDS", "20"))
HTTP_MAX_RETRIES = int(os.environ.get("HTTP_MAX_RETRIES", "3"))


class RobotsBlocked(Exception):
    pass


class TransientHTTPError(Exception):
    pass


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    content: bytes
    content_type: str


_LAST_REQUEST: dict[str, float] = defaultdict(float)
_LAST_LOCK = threading.Lock()


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().split(":")[0]


def _wait(url: str) -> None:
    if RATE_LIMIT_PER_DOMAIN_RPS <= 0:
        return
    d = _domain(url)
    gap_needed = 1.0 / RATE_LIMIT_PER_DOMAIN_RPS
    with _LAST_LOCK:
        last = _LAST_REQUEST[d]
        now = time.monotonic()
        if now - last < gap_needed:
            time.sleep(gap_needed - (now - last))
        _LAST_REQUEST[d] = time.monotonic()


_ROBOTS_CACHE: dict[str, tuple[RobotFileParser, float]] = {}
_ROBOTS_LOCK = threading.Lock()
_ROBOTS_TTL_SECONDS = 24 * 3600


def _robots_allowed(url: str) -> bool:
    p = urlparse(url)
    origin = f"{p.scheme}://{p.netloc}"
    with _ROBOTS_LOCK:
        cached = _ROBOTS_CACHE.get(origin)
        now = time.time()
        if cached and (now - cached[1]) < _ROBOTS_TTL_SECONDS:
            rp = cached[0]
        else:
            rp = RobotFileParser()
            try:
                resp = requests.get(
                    f"{origin}/robots.txt",
                    timeout=HTTP_TIMEOUT_SECONDS,
                    headers={"User-Agent": USER_AGENT},
                )
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                else:
                    rp.parse([])
            except requests.RequestException:
                rp.parse([])
            _ROBOTS_CACHE[origin] = (rp, now)
    return rp.can_fetch(USER_AGENT, url)


@retry(
    reraise=True,
    stop=stop_after_attempt(HTTP_MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    retry=retry_if_exception_type(TransientHTTPError),
)
def fetch(url: str, *, respect_robots: bool = True) -> FetchResult:
    if respect_robots and not _robots_allowed(url):
        raise RobotsBlocked(url)
    _wait(url)
    try:
        resp = requests.get(
            url,
            timeout=HTTP_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.5"},
            allow_redirects=True,
        )
    except requests.RequestException as e:
        raise TransientHTTPError(str(e)) from e
    if resp.status_code in (429, 500, 502, 503, 504):
        raise TransientHTTPError(f"HTTP {resp.status_code} from {url}")
    return FetchResult(
        url=url,
        final_url=resp.url,
        status_code=resp.status_code,
        content=resp.content,
        content_type=resp.headers.get("Content-Type", ""),
    )


def try_fetch(url: str) -> Optional[FetchResult]:
    try:
        return fetch(url)
    except RobotsBlocked:
        log.info("robots blocked: %s", url)
        return None
    except TransientHTTPError as e:
        log.info("fetch failed: %s (%s)", url, e)
        return None
    except Exception as e:
        log.warning("unexpected error fetching %s: %s", url, e)
        return None
