"""Abstract search provider so we can swap Tavily for another backend later."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str
    snippet: str
    score: float | None = None
    published_at: str | None = None


class SearchProvider(Protocol):
    def search(
        self,
        query: str,
        max_results: int = 10,
        include_domains: list[str] | None = None,
    ) -> list[SearchHit]: ...
