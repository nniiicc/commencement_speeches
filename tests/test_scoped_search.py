"""Pin the scoped-first / open-fallback behavior of Step 1 search."""
from __future__ import annotations

from commencement.discovery.step1_speaker import _candidate_pages_from_search
from commencement.search.base import SearchHit


class _Recorder:
    """Mock SearchProvider that records every call and returns canned results per call."""

    def __init__(self, responses: list[list[SearchHit]]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def search(
        self,
        query: str,
        max_results: int = 10,
        include_domains: list[str] | None = None,
    ) -> list[SearchHit]:
        self.calls.append(
            {"query": query, "max_results": max_results, "include_domains": include_domains}
        )
        return self._responses.pop(0) if self._responses else []


def test_scoped_search_used_first_when_homepage_present():
    scoped_hit = SearchHit(url="https://harvard.edu/a", title="t", snippet="s")
    provider = _Recorder([[scoped_hit]])
    out = _candidate_pages_from_search(
        "Harvard University", "https://www.harvard.edu/", provider
    )
    assert out == [scoped_hit]
    assert len(provider.calls) == 1
    assert provider.calls[0]["include_domains"] == ["harvard.edu"]


def test_falls_back_to_open_when_scoped_empty():
    open_hit = SearchHit(url="https://news.example.com/x", title="t", snippet="s")
    provider = _Recorder([[], [open_hit]])
    out = _candidate_pages_from_search(
        "Harvard University", "https://www.harvard.edu/", provider
    )
    assert out == [open_hit]
    assert len(provider.calls) == 2
    assert provider.calls[0]["include_domains"] == ["harvard.edu"]
    assert provider.calls[1]["include_domains"] is None


def test_open_search_only_when_no_homepage():
    open_hit = SearchHit(url="https://news.example.com/x", title="t", snippet="s")
    provider = _Recorder([[open_hit]])
    out = _candidate_pages_from_search("Some Institution", None, provider)
    assert out == [open_hit]
    assert len(provider.calls) == 1
    assert provider.calls[0]["include_domains"] is None


def test_open_search_only_when_homepage_unparseable():
    open_hit = SearchHit(url="https://news.example.com/x", title="t", snippet="s")
    provider = _Recorder([[open_hit]])
    # registered_domain returns None for malformed input → skip scoped pass entirely
    out = _candidate_pages_from_search("Some Institution", "not-a-url", provider)
    assert out == [open_hit]
    assert len(provider.calls) == 1
    assert provider.calls[0]["include_domains"] is None
