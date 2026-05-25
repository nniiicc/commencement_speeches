"""Step 1: speaker identification.

Per institution: search the web, probe news subdomain, fetch top pages, run LLM
extraction, write ceremony + speaker rows.
"""
from __future__ import annotations

import logging
from datetime import datetime

import trafilatura
from sqlalchemy import select

from commencement.common.http_client import try_fetch
from commencement.common.normalize import (
    domain_matches,
    normalize_name,
    registered_domain,
)
from commencement.config import CONFIG
from commencement.db.models import (
    Ceremony,
    CeremonySpeaker,
    CeremonyStatus,
    CeremonyType,
    DiscardedCandidate,
    IdentityMethod,
    Institution,
    Source,
    SourceKind,
    Speaker,
)
from commencement.db.session import get_session
from commencement.llm.extract import SpeakerExtraction, extract_speaker
from commencement.search.base import SearchHit, SearchProvider
from commencement.storage import BlobStore

log = logging.getLogger(__name__)


def _ceremony_status_from_date(d: datetime | None) -> CeremonyStatus:
    if d is None:
        return CeremonyStatus.unknown
    return CeremonyStatus.past if d.date() < datetime.utcnow().date() else CeremonyStatus.future


def _parse_iso_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None


def _news_subdomain_candidates(homepage_url: str | None) -> list[str]:
    if not homepage_url:
        return []
    domain = registered_domain(homepage_url)
    if not domain:
        return []
    return [f"https://news.{domain}/", f"https://{domain}/news"]


def _identity_method_for(
    extraction: SpeakerExtraction, institution_homepage: str | None
) -> IdentityMethod:
    if extraction.is_official_institution_source:
        return IdentityMethod.official_press_release
    if institution_homepage and extraction.source_url:
        if domain_matches(institution_homepage, extraction.source_url):
            return IdentityMethod.institutional_news
    if extraction.speaker_name:
        return IdentityMethod.third_party_news
    return IdentityMethod.none


def _candidate_pages_from_search(
    institution_name: str,
    homepage_url: str | None,
    search_provider: SearchProvider,
    year: int = CONFIG.PILOT_YEAR,
) -> list[SearchHit]:
    """Scoped to institution domain first; open search only if scoped is empty.

    Scoping kills cross-institution name collisions (Bethel-IN vs Bethel-TN,
    Drew vs Charles R Drew, Wesleyan U CT vs Wesleyan College GA, etc.).
    Open fallback preserves the legitimate third-party-news case (e.g., a
    Senator's office press release announcing the speaker).
    """
    query = f'"{institution_name}" commencement speaker {year}'
    domain = registered_domain(homepage_url) if homepage_url else None
    if domain:
        scoped = search_provider.search(
            query, max_results=10, include_domains=[domain]
        )
        if scoped:
            log.debug("step1: scoped search returned %d hits on %s", len(scoped), domain)
            return scoped
    log.debug("step1: scoped search empty (or no homepage); falling back to open search")
    return search_provider.search(query, max_results=10)


def _fetch_pages(
    urls: list[str], blob_store: BlobStore, max_pages: int = 3
) -> list[dict]:
    out: list[dict] = []
    for url in urls[:max_pages]:
        result = try_fetch(url)
        if not result or result.status_code != 200:
            continue
        try:
            text = trafilatura.extract(result.content.decode("utf-8", errors="ignore")) or ""
        except Exception:
            text = ""
        ref = None
        try:
            ref = blob_store.put(result.content, kind="html")
        except Exception:
            pass
        out.append(
            {
                "url": result.final_url,
                "text": text,
                "content_hash": ref.content_hash if ref else None,
                "bytes_len": ref.bytes_len if ref else None,
                "storage_path": ref.storage_path if ref else None,
            }
        )
    return out


def _record_source_rows(session, pages: list[dict]) -> None:
    for p in pages:
        if not p.get("content_hash"):
            continue
        existing = session.get(Source, p["content_hash"])
        if existing:
            continue
        session.add(
            Source(
                content_hash=p["content_hash"],
                kind=SourceKind.html,
                url=p["url"],
                bytes_len=p["bytes_len"],
                storage_path=p["storage_path"],
            )
        )


def _upsert_speaker(
    session, speaker_name: str, speaker_role: str | None
) -> Speaker | None:
    """Upsert a Speaker keyed by normalized_name. One row per real-world person."""
    if not speaker_name:
        return None
    norm = normalize_name(speaker_name)
    existing = (
        session.execute(select(Speaker).where(Speaker.normalized_name == norm))
        .scalars()
        .first()
    )
    if existing:
        if speaker_role and not existing.speaker_role:
            existing.speaker_role = speaker_role
        return existing
    sp = Speaker(
        display_name=speaker_name,
        normalized_name=norm,
        speaker_role=speaker_role,
    )
    session.add(sp)
    session.flush()
    return sp


def resolve_speaker_for_institution(
    institution: Institution,
    search_provider: SearchProvider,
    blob_store: BlobStore | None = None,
    year: int = CONFIG.PILOT_YEAR,
) -> dict:
    blob_store = blob_store or BlobStore()
    institution_name = institution.name
    ipeds_id = institution.ipeds_id

    log.info("step1: resolving speaker for %s (ipeds_id=%d, year=%d)", institution_name, ipeds_id, year)

    hits = _candidate_pages_from_search(
        institution_name, institution.homepage_url, search_provider, year=year
    )
    candidate_urls = [h.url for h in hits if h.url]

    candidate_urls.extend(_news_subdomain_candidates(institution.homepage_url))

    pages_with_text = _fetch_pages(candidate_urls, blob_store=blob_store, max_pages=3)
    for h in hits[:6]:
        pages_with_text.append(
            {"url": h.url, "title": h.title, "snippet": h.snippet, "text": ""}
        )

    if not pages_with_text:
        log.info("step1: no candidate pages for %s", institution_name)
        extraction = None
    else:
        extraction = extract_speaker(institution_name, pages_with_text, year=year)

    with get_session() as session:
        existing = (
            session.execute(
                select(Ceremony).where(
                    Ceremony.ipeds_id == ipeds_id,
                    Ceremony.year == year,
                )
            )
            .scalars()
            .first()
        )

        if extraction and extraction.ceremony_type == "per_college":
            session.add(
                DiscardedCandidate(
                    ipeds_id=ipeds_id,
                    reason="per_college",
                    source_url=extraction.source_url,
                    raw_extract=extraction.__dict__,
                )
            )
            return {"ipeds_id": ipeds_id, "status": "discarded_per_college"}

        ceremony_date = _parse_iso_date(extraction.ceremony_date) if extraction else None
        ceremony_status = _ceremony_status_from_date(ceremony_date)

        if existing is None:
            ceremony = Ceremony(
                ipeds_id=ipeds_id,
                year=year,
                ceremony_date=ceremony_date,
                ceremony_status=ceremony_status,
                ceremony_type=(
                    CeremonyType.universitywide
                    if extraction and extraction.ceremony_type == "universitywide"
                    else CeremonyType.unknown
                ),
                last_discovery_run_at=datetime.utcnow(),
                notes=extraction.notes if extraction else None,
            )
            session.add(ceremony)
            session.flush()
        else:
            ceremony = existing
            ceremony.ceremony_date = ceremony_date or ceremony.ceremony_date
            ceremony.ceremony_status = ceremony_status
            if extraction:
                ceremony.ceremony_type = (
                    CeremonyType.universitywide
                    if extraction.ceremony_type == "universitywide"
                    else ceremony.ceremony_type
                )
                ceremony.notes = extraction.notes or ceremony.notes
            ceremony.last_discovery_run_at = datetime.utcnow()

        # Speaker identity → ceremony_speakers + speakers (3NF: identity is a
        # property of the speaker-at-ceremony link, not the ceremony row).
        if extraction and extraction.speaker_name:
            speaker = _upsert_speaker(
                session, extraction.speaker_name, extraction.speaker_role
            )
            existing_primary = (
                session.execute(
                    select(CeremonySpeaker).where(
                        CeremonySpeaker.ceremony_id == ceremony.ceremony_id,
                        CeremonySpeaker.is_primary.is_(True),
                    )
                )
                .scalars()
                .first()
            )
            if existing_primary is None:
                session.add(CeremonySpeaker(
                    ceremony_id=ceremony.ceremony_id,
                    speaker_id=speaker.speaker_id,
                    is_primary=True,
                    source_url=extraction.source_url,
                    identity_method=_identity_method_for(
                        extraction, institution.homepage_url
                    ),
                    identity_confidence=extraction.confidence,
                    notes=extraction.notes,
                ))
            elif extraction.confidence > existing_primary.identity_confidence:
                existing_primary.speaker_id = speaker.speaker_id
                existing_primary.source_url = extraction.source_url
                existing_primary.identity_method = _identity_method_for(
                    extraction, institution.homepage_url
                )
                existing_primary.identity_confidence = extraction.confidence
                existing_primary.notes = extraction.notes

        _record_source_rows(session, pages_with_text)

        session.flush()
        ceremony_id = ceremony.ceremony_id

    return {
        "ipeds_id": ipeds_id,
        "ceremony_id": ceremony_id,
        "status": "resolved" if (extraction and extraction.speaker_name) else "unresolved",
        "confidence": extraction.confidence if extraction else 0.0,
    }


