"""Optional site-restricted search fallback via Tavily."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class SearchHit:
    url: str
    title: str
    snippet: str


def search_site_restricted(domain: str, max_results: int = 10) -> list[SearchHit]:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        log.info("TAVILY_API_KEY not set, fallback search disabled")
        return []
    try:
        from tavily import TavilyClient
    except ImportError:
        log.warning("tavily-python not installed; fallback search disabled")
        return []
    client = TavilyClient(api_key=api_key)
    query = '"commencement speakers" OR "commencement addresses" list history archive'
    try:
        resp = client.search(
            query=query,
            max_results=max_results,
            search_depth="basic",
            include_domains=[domain],
        )
    except Exception as e:
        log.warning("Tavily search failed for %s: %s", domain, e)
        return []
    out: list[SearchHit] = []
    for r in resp.get("results", []):
        if r.get("url"):
            out.append(SearchHit(
                url=r["url"],
                title=r.get("title", ""),
                snippet=r.get("content", "") or r.get("snippet", ""),
            ))
    return out
