"""Step 2: transcript link discovery.

Tier 1: institutional transcript pages. Tier 2: C-SPAN program/caption pages.
We RECORD links only. Fetching and cleaning text is a downstream pipeline.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Iterable

from sqlalchemy import select

from commencement.common.http_client import try_fetch
from commencement.common.normalize import domain_matches
from commencement.config import CONFIG
from commencement.db.models import (
    Ceremony,
    Institution,
    LinkStatus,
    TranscriptKind,
    TranscriptLink,
)
from commencement.db.session import get_session
from commencement.search.base import SearchHit, SearchProvider

log = logging.getLogger(__name__)


TRANSCRIPT_ANCHOR_RE = re.compile(
    r"\b(transcript|remarks|address|speech|full[\s-]?text)\b", re.IGNORECASE
)


def _is_transcript_url(url: str) -> bool:
    return bool(TRANSCRIPT_ANCHOR_RE.search(url))


def _classify_transcript_kind(url: str) -> TranscriptKind:
    u = url.lower()
    if "c-span.org" in u or "cspan.org" in u:
        return TranscriptKind.cspan_page
    if u.endswith(".pdf"):
        return TranscriptKind.pdf
    return TranscriptKind.institutional_html


def _tier1_searches(institution_name: str, speaker_name: str | None) -> list[str]:
    year = CONFIG.PILOT_YEAR
    queries = [
        f'"{institution_name}" commencement {year} transcript',
        f'"{institution_name}" commencement {year} address text',
        f'"{institution_name}" {year} commencement remarks',
    ]
    if speaker_name:
        queries.append(f'"{institution_name}" {year} commencement "{speaker_name}" remarks')
        queries.append(f'"{speaker_name}" "{institution_name}" commencement transcript')
    return queries


def _filter_tier1(
    hits: Iterable[SearchHit], institution_homepage: str | None
) -> list[SearchHit]:
    keep: list[SearchHit] = []
    for h in hits:
        if not h.url:
            continue
        if "graduationwisdom.com" in h.url or "npr.org" in h.url:
            continue
        title_text = (h.title + " " + h.snippet).lower()
        url_text = h.url.lower()
        text_has_keyword = (
            "transcript" in title_text
            or "remarks" in title_text
            or "address" in title_text
            or "full text" in title_text
            or "speech" in title_text
        )
        url_has_keyword = _is_transcript_url(h.url)
        if not (text_has_keyword or url_has_keyword):
            continue
        if institution_homepage and domain_matches(institution_homepage, h.url):
            keep.append(h)
            continue
        keep.append(h)
    return keep


def _tier2_search_cspan(
    institution_name: str, speaker_name: str | None, search_provider: SearchProvider
) -> list[SearchHit]:
    q = f"site:c-span.org {speaker_name or ''} {institution_name} commencement {CONFIG.PILOT_YEAR}"
    return search_provider.search(q, max_results=10)


def _maybe_attach_cspan_caption(program_url: str) -> str | None:
    """C-SPAN program pages sometimes link to a caption transcript. Look at the
    page body once and grab any 'transcript' anchor that points within c-span.org."""
    result = try_fetch(program_url)
    if not result or result.status_code != 200:
        return None
    try:
        body = result.content.decode("utf-8", errors="ignore")
    except Exception:
        return None
    m = re.search(
        r'href="([^"]+)"[^>]*>[^<]*transcript', body, re.IGNORECASE
    )
    if not m:
        return None
    href = m.group(1)
    if href.startswith("/"):
        return f"https://www.c-span.org{href}"
    return href if "c-span" in href else None


def discover_transcript_links(
    ceremony: Ceremony,
    institution: Institution,
    search_provider: SearchProvider,
) -> dict:
    if (
        ceremony.identity_confidence == 0.0
        and ceremony.ceremony_status.value == "future"
    ):
        log.info(
            "step2: skipping ceremony %d (unresolved + future)", ceremony.ceremony_id
        )
        return {"ceremony_id": ceremony.ceremony_id, "status": "skipped"}

    speaker = ceremony.speaker_name
    institution_name = institution.name

    log.info(
        "step2: discovering transcript links for %s (ceremony_id=%d)",
        institution_name,
        ceremony.ceremony_id,
    )

    discovered: list[tuple[str, TranscriptKind, int]] = []

    for q in _tier1_searches(institution_name, speaker):
        hits = search_provider.search(q, max_results=10)
        for h in _filter_tier1(hits, institution.homepage_url):
            discovered.append((h.url, _classify_transcript_kind(h.url), 1))

    if speaker:
        for h in _tier2_search_cspan(institution_name, speaker, search_provider):
            if "c-span.org" not in h.url:
                continue
            discovered.append((h.url, TranscriptKind.cspan_page, 2))
            caption_url = _maybe_attach_cspan_caption(h.url)
            if caption_url:
                discovered.append((caption_url, TranscriptKind.cspan_caption, 2))

    seen: set[str] = set()
    deduped: list[tuple[str, TranscriptKind, int]] = []
    for url, kind, tier in discovered:
        if url in seen:
            continue
        seen.add(url)
        deduped.append((url, kind, tier))

    with get_session() as session:
        existing_urls = {
            r[0]
            for r in session.execute(
                select(TranscriptLink.url).where(
                    TranscriptLink.ceremony_id == ceremony.ceremony_id
                )
            ).all()
        }
        for url, kind, tier in deduped:
            if url in existing_urls:
                continue
            session.add(
                TranscriptLink(
                    ceremony_id=ceremony.ceremony_id,
                    ipeds_id=ceremony.ipeds_id,
                    source_tier=tier,
                    source_kind=kind,
                    url=url,
                    discovered_at=datetime.utcnow(),
                )
            )

        cer = session.get(Ceremony, ceremony.ceremony_id)
        cer.transcript_link_status = (
            LinkStatus.found if deduped else LinkStatus.not_found
        )

    return {
        "ceremony_id": ceremony.ceremony_id,
        "status": "found" if deduped else "not_found",
        "count": len(deduped),
    }
