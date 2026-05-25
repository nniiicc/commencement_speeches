"""Simple per-domain token bucket. Thread-safe enough for Prefect tasks running concurrently."""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from urllib.parse import urlparse

from commencement.config import CONFIG


class DomainRateLimiter:
    def __init__(self, requests_per_second: float = CONFIG.RATE_LIMIT_PER_DOMAIN) -> None:
        self.rps = requests_per_second
        self._last_request: dict[str, float] = defaultdict(float)
        self._lock = threading.Lock()

    def _domain(self, url: str) -> str:
        netloc = urlparse(url).netloc.lower()
        return netloc.split(":")[0]

    def wait(self, url: str) -> None:
        if self.rps <= 0:
            return
        domain = self._domain(url)
        min_gap = 1.0 / self.rps
        with self._lock:
            last = self._last_request[domain]
            now = time.monotonic()
            gap = now - last
            if gap < min_gap:
                time.sleep(min_gap - gap)
            self._last_request[domain] = time.monotonic()


RATE_LIMITER = DomainRateLimiter()
