"""Manual discovery helpers.

Bypasses the Tavily+Anthropic pipeline so Step 1 (speaker identity) and Step 2
(transcript links) results sourced from interactive web searches can be written
directly into the SQLite DB. Schema rules (link status tri-state, identity
method enum, append-only links) are enforced here so the chat-side caller only
has to pass facts.

Usage from a shell one-liner:

    from commencement.manual import list_pilot_pending, record_speaker, ...
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from commencement.config import CONFIG
from commencement.db.models import (
    Ceremony,
    CeremonySpeaker,
    CeremonyStatus,
    CeremonyType,
    DiscardedCandidate,
    IdentityMethod,
    Institution,
    LinkStatus,
    TranscriptKind,
    TranscriptLink,
    VideoLink,
    VideoPlatform,
)
from commencement.db.session import get_session


def _parse_dt(value: str | None) -> datetime | None:
    """Accept ISO date or datetime strings."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.strptime(value, "%Y-%m-%d")


def list_pilot_pending(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Return pilot institutions that don't yet have a pilot-year ceremony row.

    Ordered by ipeds_id for stable pagination.
    """
    with get_session() as session:
        existing_ceremony = select(Ceremony.ipeds_id).where(Ceremony.year == CONFIG.PILOT_YEAR)
        discarded = select(DiscardedCandidate.ipeds_id)
        stmt = (
            select(
                Institution.ipeds_id,
                Institution.name,
                Institution.state,
                Institution.control,
                Institution.carnegie_classification,
                Institution.homepage_url,
            )
            .where(
                Institution.in_pilot.is_(True),
                Institution.ipeds_id.not_in(existing_ceremony),
                Institution.ipeds_id.not_in(discarded),
            )
            .order_by(Institution.ipeds_id)
            .limit(limit)
            .offset(offset)
        )
        rows = session.execute(stmt).all()
    return [
        {
            "ipeds_id": r.ipeds_id,
            "name": r.name,
            "state": r.state,
            "control": r.control.value,
            "carnegie": r.carnegie_classification,
            "homepage_url": r.homepage_url,
        }
        for r in rows
    ]


def pilot_progress() -> dict[str, int]:
    """Counts for the pilot year: total pilot, ceremonies created, resolved, etc."""
    with get_session() as session:
        n_pilot = session.scalar(
            select(func.count(Institution.ipeds_id)).where(
                Institution.in_pilot.is_(True)
            )
        )
        n_ceremonies = session.scalar(
            select(func.count(Ceremony.ceremony_id)).where(
                Ceremony.year == CONFIG.PILOT_YEAR
            )
        )
        n_speakers = session.scalar(
            select(func.count(Ceremony.ceremony_id)).where(
                Ceremony.year == CONFIG.PILOT_YEAR,
                Ceremony.speaker_name.is_not(None),
            )
        )
        n_tx_found = session.scalar(
            select(func.count(Ceremony.ceremony_id)).where(
                Ceremony.year == CONFIG.PILOT_YEAR,
                Ceremony.transcript_link_status == LinkStatus.found,
            )
        )
    return {
        "pilot_institutions": int(n_pilot or 0),
        "ceremonies_created": int(n_ceremonies or 0),
        "speakers_resolved": int(n_speakers or 0),
        "transcript_links_found": int(n_tx_found or 0),
    }


def _upsert_ceremony(
    session,
    *,
    ipeds_id: int,
    speaker_name: str | None,
    source_url: str | None,
    method: IdentityMethod,
    confidence: float,
    ceremony_date: datetime | None,
    ceremony_status: CeremonyStatus,
    notes: str | None,
) -> Ceremony:
    cer = (
        session.execute(
            select(Ceremony).where(
                Ceremony.ipeds_id == ipeds_id,
                Ceremony.year == CONFIG.PILOT_YEAR,
            )
        )
        .scalars()
        .first()
    )
    if cer is None:
        cer = Ceremony(
            ipeds_id=ipeds_id,
            year=CONFIG.PILOT_YEAR,
            ceremony_type=CeremonyType.universitywide,
        )
        session.add(cer)
    cer.speaker_name = speaker_name
    cer.identity_source_url = source_url
    cer.identity_method = method
    cer.identity_confidence = confidence
    cer.ceremony_date = ceremony_date
    cer.ceremony_status = ceremony_status
    cer.notes = notes
    cer.last_discovery_run_at = datetime.utcnow()
    session.flush()
    return cer


def record_speaker(
    ipeds_id: int,
    *,
    speaker_name: str,
    source_url: str,
    method: str,
    confidence: float,
    ceremony_date: str | None = None,
    ceremony_status: str = "future",
    notes: str | None = None,
) -> int:
    """Upsert pilot-year ceremony with a resolved speaker. Returns ceremony_id.

    method must be one of: official_press_release, institutional_news, third_party_news.
    ceremony_status must be one of: past, future, unknown.
    """
    method_enum = IdentityMethod(method)
    if method_enum is IdentityMethod.none:
        raise ValueError("use record_no_speaker_found for unresolved cases")
    status_enum = CeremonyStatus(ceremony_status)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be in [0,1], got {confidence}")
    with get_session() as session:
        cer = _upsert_ceremony(
            session,
            ipeds_id=ipeds_id,
            speaker_name=speaker_name.strip(),
            source_url=source_url,
            method=method_enum,
            confidence=confidence,
            ceremony_date=_parse_dt(ceremony_date),
            ceremony_status=status_enum,
            notes=notes,
        )
        return cer.ceremony_id


def record_no_speaker_found(
    ipeds_id: int,
    *,
    ceremony_status: str = "future",
    notes: str | None = None,
) -> int:
    """Create a pilot-year ceremony row indicating Step 1 found nothing.

    Sets link statuses to not_found as well: since we already did the
    universitywide search and came up empty, transcript/video links will
    by definition not exist for this ceremony yet. `--mode catch-late` will
    pick it up later via low confidence + not_found.
    """
    with get_session() as session:
        cer = _upsert_ceremony(
            session,
            ipeds_id=ipeds_id,
            speaker_name=None,
            source_url=None,
            method=IdentityMethod.none,
            confidence=0.0,
            ceremony_date=None,
            ceremony_status=CeremonyStatus(ceremony_status),
            notes=notes,
        )
        cer.transcript_link_status = LinkStatus.not_found
        cer.video_link_status = LinkStatus.not_found
        session.flush()
        return cer.ceremony_id


def add_transcript_link(
    ceremony_id: int,
    *,
    url: str,
    tier: int,
    kind: str,
    verified_main_ceremony: bool = False,
) -> int:
    """Append a transcript_links row and set ceremony.transcript_link_status=found.

    tier: 1=institutional, 2=C-SPAN, 3=other third-party.
    kind: institutional_html | cspan_caption | cspan_page | pdf | other
    """
    if tier not in (1, 2, 3):
        raise ValueError(f"tier must be 1, 2, or 3; got {tier}")
    kind_enum = TranscriptKind(kind)
    with get_session() as session:
        cer = session.get(Ceremony, ceremony_id)
        if cer is None:
            raise ValueError(f"no ceremony_id={ceremony_id}")
        link = TranscriptLink(
            ceremony_id=ceremony_id,
            ipeds_id=cer.ipeds_id,
            source_tier=tier,
            source_kind=kind_enum,
            url=url,
            verified_main_ceremony=verified_main_ceremony,
        )
        session.add(link)
        cer.transcript_link_status = LinkStatus.found
        session.flush()
        return link.transcript_link_id


def mark_transcript_not_found(ceremony_id: int) -> None:
    """Set transcript_link_status=not_found after a real search."""
    with get_session() as session:
        cer = session.get(Ceremony, ceremony_id)
        if cer is None:
            raise ValueError(f"no ceremony_id={ceremony_id}")
        cer.transcript_link_status = LinkStatus.not_found


def add_video_link(
    ceremony_id: int,
    *,
    url: str,
    platform: str,
    tier: int = 3,
    is_full_ceremony: bool | None = None,
    duration_seconds: int | None = None,
    published_at: str | None = None,
) -> int:
    """Append a video_links row and set ceremony.video_link_status=found.

    tier: 1=institutional channel, 2=C-SPAN, 3=other third-party.
    platform: youtube | vimeo | panopto | kaltura | institutional_player |
              livestream_archive | other
    Dedupes on (ceremony_id, url): an existing row's id is returned unchanged.
    """
    if tier not in (1, 2, 3):
        raise ValueError(f"tier must be 1, 2, or 3; got {tier}")
    platform_enum = VideoPlatform(platform)
    with get_session() as session:
        cer = session.get(Ceremony, ceremony_id)
        if cer is None:
            raise ValueError(f"no ceremony_id={ceremony_id}")
        existing = (
            session.execute(
                select(VideoLink).where(
                    VideoLink.ceremony_id == ceremony_id, VideoLink.url == url
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            cer.video_link_status = LinkStatus.found
            return existing.video_link_id
        link = VideoLink(
            ceremony_id=ceremony_id,
            ipeds_id=cer.ipeds_id,
            source_tier=tier,
            platform=platform_enum,
            url=url,
            published_at=_parse_dt(published_at),
            duration_seconds=duration_seconds,
            is_full_ceremony=is_full_ceremony,
        )
        session.add(link)
        cer.video_link_status = LinkStatus.found
        session.flush()
        return link.video_link_id


def mark_video_not_found(ceremony_id: int) -> None:
    """Set video_link_status=not_found after a real search."""
    with get_session() as session:
        cer = session.get(Ceremony, ceremony_id)
        if cer is None:
            raise ValueError(f"no ceremony_id={ceremony_id}")
        cer.video_link_status = LinkStatus.not_found


def list_pending_for_video(
    *, include_future: bool = False, limit: int = 200
) -> list[dict[str, Any]]:
    """Pilot-year ceremonies with a named speaker and no video link yet.

    Excludes future-dated by default (no recording yet exists). One row per
    ceremony — school-level ceremonies surface once with the count of child
    speakers so the caller knows the recording will be multi-speaker.
    """
    with get_session() as session:
        child_count = (
            select(
                CeremonySpeaker.ceremony_id,
                func.count(CeremonySpeaker.id).label("n_children"),
            )
            .group_by(CeremonySpeaker.ceremony_id)
            .subquery()
        )
        stmt = (
            select(
                Ceremony.ceremony_id,
                Institution.ipeds_id,
                Institution.name,
                Ceremony.speaker_name,
                Ceremony.ceremony_date,
                Ceremony.ceremony_status,
                Ceremony.ceremony_type,
                Institution.homepage_url,
                Institution.youtube_channel_url,
                child_count.c.n_children,
            )
            .join(Institution, Institution.ipeds_id == Ceremony.ipeds_id)
            .join(
                child_count, child_count.c.ceremony_id == Ceremony.ceremony_id, isouter=True
            )
            .where(
                Ceremony.year == CONFIG.PILOT_YEAR,
                Ceremony.speaker_name.is_not(None),
                Ceremony.video_link_status != LinkStatus.found,
            )
            .order_by(Ceremony.ceremony_id)
            .limit(limit)
        )
        if not include_future:
            stmt = stmt.where(Ceremony.ceremony_status != CeremonyStatus.future)
        rows = session.execute(stmt).all()
    return [
        {
            "ceremony_id": r.ceremony_id,
            "ipeds_id": r.ipeds_id,
            "institution_name": r.name,
            "speaker_name": r.speaker_name,
            "ceremony_date": r.ceremony_date.date().isoformat() if r.ceremony_date else None,
            "ceremony_status": r.ceremony_status.value,
            "ceremony_type": r.ceremony_type.value,
            "homepage_url": r.homepage_url,
            "youtube_channel_url": r.youtube_channel_url,
            "child_speaker_count": int(r.n_children or 0),
        }
        for r in rows
    ]


def record_school_level_ceremony(
    ipeds_id: int,
    *,
    speakers: list[dict],
    ceremony_status: str = "past",
    ceremony_date: str | None = None,
    notes: str | None = None,
) -> int:
    """Record a ceremony whose speakers are all school/college-level (no universitywide keynote).

    `speakers` is a list of dicts with keys:
        speaker_name (required), school_or_college, ceremony_label, source_url,
        method (str), confidence (float), notes

    Sets ceremony_type = school_level_only. Ceremony.speaker_name is set to the
    first speaker's name as a convenience handle; the full list lives in
    ceremony_speakers. Returns ceremony_id.
    """
    if not speakers:
        raise ValueError("at least one speaker required")
    with get_session() as session:
        cer = (
            session.execute(
                select(Ceremony).where(
                    Ceremony.ipeds_id == ipeds_id,
                    Ceremony.year == CONFIG.PILOT_YEAR,
                )
            )
            .scalars()
            .first()
        )
        if cer is None:
            cer = Ceremony(
                ipeds_id=ipeds_id,
                year=CONFIG.PILOT_YEAR,
            )
            session.add(cer)
        cer.ceremony_type = CeremonyType.school_level_only
        cer.ceremony_status = CeremonyStatus(ceremony_status)
        cer.ceremony_date = _parse_dt(ceremony_date)
        cer.speaker_name = speakers[0]["speaker_name"]
        cer.identity_source_url = speakers[0].get("source_url")
        cer.identity_method = IdentityMethod(speakers[0].get("method", "official_press_release"))
        cer.identity_confidence = float(speakers[0].get("confidence", 0.0))
        cer.notes = notes
        cer.last_discovery_run_at = datetime.utcnow()
        session.flush()
        # Clear any prior school_speakers (idempotent upsert)
        for old in list(cer.school_speakers):
            session.delete(old)
        session.flush()
        for sp in speakers:
            row = CeremonySpeaker(
                ceremony_id=cer.ceremony_id,
                speaker_name=sp["speaker_name"],
                school_or_college=sp.get("school_or_college"),
                ceremony_label=sp.get("ceremony_label"),
                source_url=sp.get("source_url"),
                identity_method=IdentityMethod(sp.get("method", "official_press_release")),
                identity_confidence=float(sp.get("confidence", 0.0)),
                notes=sp.get("notes"),
            )
            session.add(row)
        session.flush()
        return cer.ceremony_id


def discard_per_college(
    ipeds_id: int,
    *,
    source_url: str | None,
    reason: str = "per_college_ceremony",
    raw_extract: dict | None = None,
) -> int:
    """Record a candidate we threw out because it was not a universitywide ceremony."""
    with get_session() as session:
        row = DiscardedCandidate(
            ipeds_id=ipeds_id,
            reason=reason,
            source_url=source_url,
            raw_extract=raw_extract,
        )
        session.add(row)
        session.flush()
        return row.id
