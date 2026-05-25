"""Tavily search provider."""
from __future__ import annotations

import logging
from typing import Any

from commencement.config import CONFIG
from commencement.search.base import SearchHit

log = logging.getLogger(__name__)


class TavilySearchProvider:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or CONFIG.TAVILY_API_KEY
        if not self.api_key:
            raise RuntimeError("TAVILY_API_KEY not set")
        try:
            from tavily import TavilyClient
        except ImportError as e:
            raise RuntimeError("tavily-python is not installed") from e
        self._client = TavilyClient(api_key=self.api_key)

    def search(
        self,
        query: str,
        max_results: int = 10,
        include_domains: list[str] | None = None,
    ) -> list[SearchHit]:
        kwargs: dict[str, Any] = {
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
        }
        if include_domains:
            kwargs["include_domains"] = include_domains
        try:
            resp: dict[str, Any] = self._client.search(**kwargs)
        except Exception as e:
            log.warning("Tavily search failed for %r: %s", query, e)
            return []

        hits: list[SearchHit] = []
        for r in resp.get("results", []):
            hits.append(
                SearchHit(
                    url=r.get("url", ""),
                    title=r.get("title", ""),
                    snippet=r.get("content", "") or r.get("snippet", ""),
                    score=r.get("score"),
                    published_at=r.get("published_date"),
                )
            )
        return hits


def get_search_provider() -> TavilySearchProvider:
    if CONFIG.WEB_SEARCH_PROVIDER == "tavily":
        return TavilySearchProvider()
    raise RuntimeError(f"unknown search provider: {CONFIG.WEB_SEARCH_PROVIDER}")
