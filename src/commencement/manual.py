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

from commencement.common.normalize import normalize_name
from commencement.config import CONFIG
from commencement.db.models import (
    Ceremony,
    CeremonySpeaker,
    CeremonyStatus,
    CeremonyType,
    DiscardedCandidate,
    IdentityMethod,
    Institution,
    Speaker,
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


def list_pilot_pending(
    limit: int = 50,
    offset: int = 0,
    *,
    year: int = CONFIG.PILOT_YEAR,
) -> list[dict[str, Any]]:
    """Return pilot institutions that don't yet have a ceremony row for `year`.

    Ordered by ipeds_id for stable pagination.
    """
    with get_session() as session:
        existing_ceremony = select(Ceremony.ipeds_id).where(Ceremony.year == year)
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


def pilot_progress(*, year: int = CONFIG.PILOT_YEAR) -> dict[str, int]:
    """Counts for the given year: total pilot, ceremonies created, resolved, etc."""
    with get_session() as session:
        n_pilot = session.scalar(
            select(func.count(Institution.ipeds_id)).where(
                Institution.in_pilot.is_(True)
            )
        )
        n_ceremonies = session.scalar(
            select(func.count(Ceremony.ceremony_id)).where(Ceremony.year == year)
        )
        # speakers_resolved: ceremonies that have at least one CeremonySpeaker row.
        n_speakers = session.scalar(
            select(func.count(func.distinct(Ceremony.ceremony_id)))
            .join(CeremonySpeaker, CeremonySpeaker.ceremony_id == Ceremony.ceremony_id)
            .where(Ceremony.year == year)
        )
        # transcript_links_found: ceremonies with at least one transcript_links row.
        n_tx_found = session.scalar(
            select(func.count(func.distinct(Ceremony.ceremony_id)))
            .join(TranscriptLink, TranscriptLink.ceremony_id == Ceremony.ceremony_id)
            .where(Ceremony.year == year)
        )
    return {
        "year": year,
        "pilot_institutions": int(n_pilot or 0),
        "ceremonies_created": int(n_ceremonies or 0),
        "speakers_resolved": int(n_speakers or 0),
        "transcript_links_found": int(n_tx_found or 0),
    }


def _upsert_ceremony(
    session,
    *,
    ipeds_id: int,
    ceremony_date: datetime | None,
    ceremony_status: CeremonyStatus,
    notes: str | None,
    year: int = CONFIG.PILOT_YEAR,
    ceremony_type: CeremonyType = CeremonyType.universitywide,
) -> Ceremony:
    """Upsert a Ceremony row keyed on (ipeds_id, year). Speaker identity lives
    in `ceremony_speakers` and is set via `_upsert_ceremony_speaker`."""
    cer = (
        session.execute(
            select(Ceremony).where(
                Ceremony.ipeds_id == ipeds_id,
                Ceremony.year == year,
            )
        )
        .scalars()
        .first()
    )
    if cer is None:
        cer = Ceremony(ipeds_id=ipeds_id, year=year, ceremony_type=ceremony_type)
        session.add(cer)
    cer.ceremony_date = ceremony_date
    cer.ceremony_status = ceremony_status
    cer.notes = notes
    cer.last_discovery_run_at = datetime.utcnow()
    if ceremony_type is not None:
        cer.ceremony_type = ceremony_type
    session.flush()
    return cer


def _upsert_speaker(session, display_name: str) -> Speaker:
    """Upsert a Speaker keyed on normalized_name. One row per real-world person."""
    display_name = display_name.strip()
    norm = normalize_name(display_name)
    sp = session.execute(
        select(Speaker).where(Speaker.normalized_name == norm)
    ).scalar_one_or_none()
    if sp is None:
        sp = Speaker(normalized_name=norm, display_name=display_name)
        session.add(sp)
        session.flush()
    return sp


def _upsert_ceremony_speaker(
    session,
    *,
    ceremony: Ceremony,
    speaker: Speaker,
    is_primary: bool,
    source_url: str | None,
    method: IdentityMethod,
    confidence: float,
    school_or_college: str | None = None,
    ceremony_label: str | None = None,
    notes: str | None = None,
) -> CeremonySpeaker:
    """Upsert the (ceremony, speaker) link row."""
    cs = session.execute(
        select(CeremonySpeaker).where(
            CeremonySpeaker.ceremony_id == ceremony.ceremony_id,
            CeremonySpeaker.speaker_id == speaker.speaker_id,
        )
    ).scalar_one_or_none()
    if cs is None:
        cs = CeremonySpeaker(
            ceremony_id=ceremony.ceremony_id, speaker_id=speaker.speaker_id
        )
        session.add(cs)
    cs.is_primary = is_primary
    cs.source_url = source_url
    cs.identity_method = method
    cs.identity_confidence = confidence
    cs.school_or_college = school_or_college
    cs.ceremony_label = ceremony_label
    cs.notes = notes
    session.flush()
    return cs


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
    year: int = CONFIG.PILOT_YEAR,
) -> int:
    """Upsert (ipeds_id, year) ceremony with a resolved universitywide speaker.

    Creates a CeremonySpeaker row with `is_primary=True` linking the ceremony
    to the deduplicated Speaker row. Returns ceremony_id.

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
            ceremony_date=_parse_dt(ceremony_date),
            ceremony_status=status_enum,
            notes=notes,
            year=year,
            ceremony_type=CeremonyType.universitywide,
        )
        speaker = _upsert_speaker(session, speaker_name)
        _upsert_ceremony_speaker(
            session,
            ceremony=cer,
            speaker=speaker,
            is_primary=True,
            source_url=source_url,
            method=method_enum,
            confidence=confidence,
            notes=notes,
        )
        return cer.ceremony_id


def record_no_speaker_found(
    ipeds_id: int,
    *,
    ceremony_status: str = "future",
    notes: str | None = None,
    year: int = CONFIG.PILOT_YEAR,
) -> int:
    """Create a Ceremony row recording that Step 1 found nothing.

    Sets `transcript_searched_at` and `video_searched_at` to now: when Step 1
    fails, we count the transcript/video steps as searched-and-empty too, so
    `--mode catch-late` re-attempts the full pipeline rather than treating
    them as never-tried.
    """
    with get_session() as session:
        cer = _upsert_ceremony(
            session,
            ipeds_id=ipeds_id,
            ceremony_date=None,
            ceremony_status=CeremonyStatus(ceremony_status),
            notes=notes,
            year=year,
            ceremony_type=CeremonyType.universitywide,
        )
        now = datetime.utcnow()
        cer.transcript_searched_at = now
        cer.video_searched_at = now
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
    """Append a transcript_links row and stamp ceremony.transcript_searched_at.

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
            source_tier=tier,
            source_kind=kind_enum,
            url=url,
            verified_main_ceremony=verified_main_ceremony,
        )
        session.add(link)
        cer.transcript_searched_at = datetime.utcnow()
        session.flush()
        return link.transcript_link_id


def mark_transcript_not_found(ceremony_id: int) -> None:
    """Stamp ceremony.transcript_searched_at after a real search returned nothing."""
    with get_session() as session:
        cer = session.get(Ceremony, ceremony_id)
        if cer is None:
            raise ValueError(f"no ceremony_id={ceremony_id}")
        cer.transcript_searched_at = datetime.utcnow()


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
    """Append a video_links row and stamp ceremony.video_searched_at.

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
            cer.video_searched_at = datetime.utcnow()
            return existing.video_link_id
        link = VideoLink(
            ceremony_id=ceremony_id,
            source_tier=tier,
            platform=platform_enum,
            url=url,
            published_at=_parse_dt(published_at),
            duration_seconds=duration_seconds,
            is_full_ceremony=is_full_ceremony,
        )
        session.add(link)
        cer.video_searched_at = datetime.utcnow()
        session.flush()
        return link.video_link_id


def mark_video_not_found(ceremony_id: int) -> None:
    """Stamp ceremony.video_searched_at after a real search returned nothing."""
    with get_session() as session:
        cer = session.get(Ceremony, ceremony_id)
        if cer is None:
            raise ValueError(f"no ceremony_id={ceremony_id}")
        cer.video_searched_at = datetime.utcnow()


def list_pending_for_video(
    *,
    include_future: bool = False,
    limit: int = 200,
    year: int = CONFIG.PILOT_YEAR,
) -> list[dict[str, Any]]:
    """Ceremonies for `year` with at least one named speaker and no video link yet.

    Excludes future-dated by default (no recording yet exists). One row per
    ceremony. `child_speaker_count` is the total number of CeremonySpeaker
    rows (universitywide primary counts as 1); use it to detect multi-speaker
    school-level ceremonies.
    """
    with get_session() as session:
        speaker_counts = (
            select(
                CeremonySpeaker.ceremony_id,
                func.count(CeremonySpeaker.id).label("n_speakers"),
            )
            .group_by(CeremonySpeaker.ceremony_id)
            .subquery()
        )
        primary = (
            select(CeremonySpeaker.ceremony_id, Speaker.display_name)
            .join(Speaker, Speaker.speaker_id == CeremonySpeaker.speaker_id)
            .where(CeremonySpeaker.is_primary.is_(True))
            .subquery()
        )
        has_video = (
            select(VideoLink.ceremony_id)
            .group_by(VideoLink.ceremony_id)
            .subquery()
        )
        stmt = (
            select(
                Ceremony.ceremony_id,
                Institution.ipeds_id,
                Institution.name,
                primary.c.display_name,
                Ceremony.ceremony_date,
                Ceremony.ceremony_status,
                Ceremony.ceremony_type,
                Institution.homepage_url,
                Institution.youtube_channel_url,
                speaker_counts.c.n_speakers,
            )
            .join(Institution, Institution.ipeds_id == Ceremony.ipeds_id)
            .join(speaker_counts, speaker_counts.c.ceremony_id == Ceremony.ceremony_id)
            .join(primary, primary.c.ceremony_id == Ceremony.ceremony_id, isouter=True)
            .where(
                Ceremony.year == year,
                Ceremony.ceremony_id.not_in(select(has_video.c.ceremony_id)),
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
            "speaker_name": r.display_name,
            "ceremony_date": r.ceremony_date.date().isoformat() if r.ceremony_date else None,
            "ceremony_status": r.ceremony_status.value,
            "ceremony_type": r.ceremony_type.value,
            "homepage_url": r.homepage_url,
            "youtube_channel_url": r.youtube_channel_url,
            "child_speaker_count": int(r.n_speakers or 0),
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
    year: int = CONFIG.PILOT_YEAR,
) -> int:
    """Record an (ipeds_id, year) ceremony with multiple school-level speakers.

    `speakers` is a list of dicts with keys:
        speaker_name (required), school_or_college, ceremony_label, source_url,
        method (str), confidence (float), notes

    Sets ceremony_type = school_level_only. The first speaker is marked
    `is_primary=True` as a representative handle; the others are linked
    school-level rows. Returns ceremony_id.

    Idempotent: re-calling for the same (ipeds, year) wipes prior
    ceremony_speakers rows and rewrites from the `speakers` argument.
    """
    if not speakers:
        raise ValueError("at least one speaker required")
    with get_session() as session:
        cer = _upsert_ceremony(
            session,
            ipeds_id=ipeds_id,
            ceremony_date=_parse_dt(ceremony_date),
            ceremony_status=CeremonyStatus(ceremony_status),
            notes=notes,
            year=year,
            ceremony_type=CeremonyType.school_level_only,
        )
        # Idempotent rewrite of the speakers for this ceremony.
        for old in list(cer.ceremony_speakers):
            session.delete(old)
        session.flush()
        for idx, sp in enumerate(speakers):
            speaker = _upsert_speaker(session, sp["speaker_name"])
            _upsert_ceremony_speaker(
                session,
                ceremony=cer,
                speaker=speaker,
                is_primary=(idx == 0),
                source_url=sp.get("source_url"),
                method=IdentityMethod(sp.get("method", "official_press_release")),
                confidence=float(sp.get("confidence", 0.0)),
                school_or_college=sp.get("school_or_college"),
                ceremony_label=sp.get("ceremony_label"),
                notes=sp.get("notes"),
            )
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


def list_universitywide_speaker_ipeds(
    reference_year: int = CONFIG.PILOT_YEAR,
) -> list[int]:
    """IPEDS IDs for institutions with a named universitywide speaker in `reference_year`.

    Use this to build the historical-backfill cohort: e.g.,
    `list_universitywide_speaker_ipeds(2026)` returns the institutions to re-search
    for 2025 data. Returns IDs ordered by ipeds_id.
    """
    with get_session() as session:
        rows = session.execute(
            select(Ceremony.ipeds_id)
            .join(CeremonySpeaker, CeremonySpeaker.ceremony_id == Ceremony.ceremony_id)
            .where(
                Ceremony.year == reference_year,
                Ceremony.ceremony_type == CeremonyType.universitywide,
                CeremonySpeaker.is_primary.is_(True),
            )
            .order_by(Ceremony.ipeds_id)
        ).all()
    return [r[0] for r in rows]
