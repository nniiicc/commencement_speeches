"""robots.txt cache, refreshed daily."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from commencement.config import CONFIG


class RobotsCache:
    def __init__(self, ttl_hours: int = 24) -> None:
        self._parsers: dict[str, tuple[RobotFileParser, datetime]] = {}
        self._lock = threading.Lock()
        self._ttl = timedelta(hours=ttl_hours)

    def _origin(self, url: str) -> str:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}"

    def _fetch(self, origin: str) -> RobotFileParser:
        rp = RobotFileParser()
        robots_url = f"{origin}/robots.txt"
        try:
            resp = requests.get(
                robots_url,
                timeout=CONFIG.HTTP_TIMEOUT_SECONDS,
                headers={"User-Agent": CONFIG.USER_AGENT},
            )
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            else:
                rp.parse([])
        except requests.RequestException:
            rp.parse([])
        return rp

    def allowed(self, url: str) -> bool:
        origin = self._origin(url)
        with self._lock:
            cached = self._parsers.get(origin)
            now = datetime.utcnow()
            if cached and (now - cached[1]) < self._ttl:
                rp = cached[0]
            else:
                rp = self._fetch(origin)
                self._parsers[origin] = (rp, now)
        return rp.can_fetch(CONFIG.USER_AGENT, url)


ROBOTS = RobotsCache()
