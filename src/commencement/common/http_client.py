"""Polite HTTP client: user-agent, rate limit, robots, retries."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from commencement.common.rate_limit import RATE_LIMITER
from commencement.common.robots import ROBOTS
from commencement.config import CONFIG

log = logging.getLogger(__name__)


class RobotsBlocked(Exception):
    pass


class TransientHTTPError(Exception):
    pass


@dataclass
class FetchResult:
    url: str
    status_code: int
    content: bytes
    content_type: str
    final_url: str


@retry(
    reraise=True,
    stop=stop_after_attempt(CONFIG.HTTP_MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    retry=retry_if_exception_type(TransientHTTPError),
)
def fetch(
    url: str,
    *,
    method: str = "GET",
    timeout: int = CONFIG.HTTP_TIMEOUT_SECONDS,
    headers: Optional[dict] = None,
    respect_robots: bool = True,
) -> FetchResult:
    if respect_robots and not ROBOTS.allowed(url):
        raise RobotsBlocked(url)

    RATE_LIMITER.wait(url)
    h = {"User-Agent": CONFIG.USER_AGENT}
    if headers:
        h.update(headers)

    try:
        resp = requests.request(method, url, headers=h, timeout=timeout, allow_redirects=True)
    except requests.RequestException as e:
        raise TransientHTTPError(str(e)) from e

    if resp.status_code in (429, 500, 502, 503, 504):
        raise TransientHTTPError(f"HTTP {resp.status_code} from {url}")

    return FetchResult(
        url=url,
        status_code=resp.status_code,
        content=resp.content,
        content_type=resp.headers.get("Content-Type", ""),
        final_url=resp.url,
    )


def try_fetch(url: str, **kwargs) -> FetchResult | None:
    try:
        return fetch(url, **kwargs)
    except RobotsBlocked:
        log.info("robots blocked: %s", url)
        return None
    except TransientHTTPError as e:
        log.info("fetch failed after retries: %s (%s)", url, e)
        return None
    except Exception as e:
        log.warning("unexpected fetch error: %s (%s)", url, e)
        return None
