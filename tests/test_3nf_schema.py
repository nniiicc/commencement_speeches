"""Pin 3NF schema invariants.

After the 3NF migration:
- `speakers` is keyed by `normalized_name` (no ipeds_id coupling). One row per person.
- `ceremony_speakers` is the join table (ceremony × speaker), with `is_primary`
  flagging the universitywide-equivalent keynote.
- `transcript_link_status` / `video_link_status` are Python @properties on
  Ceremony, derived from `(*_searched_at, child rows existence)`.
- A speaker who appears at multiple institutions deduplicates to ONE
  `speakers` row.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="module")
def configured_db(tmp_path_factory):
    db_dir = tmp_path_factory.mktemp("dbcfg_3nf")
    db_path = db_dir / "test.sqlite"
    os.environ["DB_URL"] = f"sqlite:///{db_path}"
    os.environ["OBJECT_STORE_DIR"] = str(db_dir / "blobs")
    yield


def _seed(ipeds_id: int):
    from commencement.db.models import Control, Institution
    from commencement.db.session import get_session, init_schema

    init_schema()
    with get_session() as session:
        session.merge(Institution(
            ipeds_id=ipeds_id, name=f"Inst {ipeds_id}",
            control=Control.public, in_pilot=True,
        ))


def test_same_speaker_at_two_institutions_dedupes_to_one_speaker_row(configured_db):
    """The whole point of normalizing the speakers table."""
    from sqlalchemy import select
    from commencement.db.models import Speaker
    from commencement.db.session import get_session
    from commencement.manual import record_speaker

    for ipeds in (501, 502):
        _seed(ipeds)

    record_speaker(
        501, year=2025, speaker_name="Same Person",
        source_url="https://example.edu/a", method="official_press_release",
        confidence=0.9, ceremony_status="past",
    )
    record_speaker(
        502, year=2025, speaker_name="Same Person",
        source_url="https://example.edu/b", method="official_press_release",
        confidence=0.9, ceremony_status="past",
    )
    with get_session() as s:
        rows = s.execute(
            select(Speaker).where(Speaker.normalized_name == "same person")
        ).scalars().all()
        assert len(rows) == 1, "same person across institutions must dedupe"


def test_link_status_property_derives_from_timestamp_and_rows(configured_db):
    """Property contract: NULL → not_searched, set + 0 rows → not_found,
    set + ≥1 row → found."""
    from datetime import datetime
    from commencement.db.models import (
        Ceremony,
        CeremonyStatus,
        LinkStatus,
        TranscriptKind,
        TranscriptLink,
    )
    from commencement.db.session import get_session

    _seed(503)
    with get_session() as s:
        cer = Ceremony(ipeds_id=503, year=2025, ceremony_status=CeremonyStatus.past)
        s.add(cer)
        s.flush()
        cid = cer.ceremony_id

    # NULL searched_at → not_searched
    with get_session() as s:
        cer = s.get(Ceremony, cid)
        assert cer.transcript_link_status == LinkStatus.not_searched

    # Set searched_at without adding a row → not_found
    with get_session() as s:
        cer = s.get(Ceremony, cid)
        cer.transcript_searched_at = datetime.utcnow()
    with get_session() as s:
        cer = s.get(Ceremony, cid)
        assert cer.transcript_link_status == LinkStatus.not_found

    # Add a row → found
    with get_session() as s:
        s.add(TranscriptLink(
            ceremony_id=cid, source_tier=1,
            source_kind=TranscriptKind.institutional_html,
            url="https://example.edu/x",
        ))
    with get_session() as s:
        cer = s.get(Ceremony, cid)
        assert cer.transcript_link_status == LinkStatus.found


def test_speaker_name_property_returns_primary(configured_db):
    """`Ceremony.speaker_name` is the backwards-compat property returning the
    primary CeremonySpeaker's Speaker.display_name."""
    from commencement.db.models import Ceremony
    from commencement.db.session import get_session
    from commencement.manual import record_speaker

    _seed(504)
    cid = record_speaker(
        504, year=2025, speaker_name="Primary Person",
        source_url="https://example.edu/p", method="official_press_release",
        confidence=0.9, ceremony_status="past",
    )
    with get_session() as s:
        cer = s.get(Ceremony, cid)
        assert cer.speaker_name == "Primary Person"
        assert cer.primary_speaker is not None
        assert cer.primary_speaker.is_primary is True


def test_ceremony_speakers_unique_per_ceremony_speaker_pair(configured_db):
    """The unique index `(ceremony_id, speaker_id)` prevents accidental dupes."""
    from sqlalchemy.exc import IntegrityError
    from commencement.db.models import (
        Ceremony,
        CeremonySpeaker,
        CeremonyStatus,
        IdentityMethod,
        Speaker,
    )
    from commencement.db.session import get_session

    _seed(505)
    with get_session() as s:
        cer = Ceremony(ipeds_id=505, year=2025, ceremony_status=CeremonyStatus.past)
        spk = Speaker(normalized_name="dupe", display_name="Dupe Test")
        s.add_all([cer, spk])
        s.flush()
        s.add(CeremonySpeaker(
            ceremony_id=cer.ceremony_id, speaker_id=spk.speaker_id,
            is_primary=True, identity_method=IdentityMethod.official_press_release,
            identity_confidence=0.9,
        ))

    with pytest.raises(IntegrityError):
        with get_session() as s:
            # Re-create the same Ceremony/Speaker pointers and attempt a duplicate row
            from sqlalchemy import select
            cer = s.execute(select(Ceremony).where(Ceremony.ipeds_id == 505)).scalar_one()
            spk = s.execute(select(Speaker).where(Speaker.normalized_name == "dupe")).scalar_one()
            s.add(CeremonySpeaker(
                ceremony_id=cer.ceremony_id, speaker_id=spk.speaker_id,
                is_primary=False, identity_method=IdentityMethod.official_press_release,
                identity_confidence=0.5,
            ))
