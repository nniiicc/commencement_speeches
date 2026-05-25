"""Verify the --mode filters return the right institutions under the 3NF schema.

Post-3NF, the catch-late filter no longer reads `Ceremony.identity_confidence`
or `Ceremony.transcript_link_status`; it reads `CeremonySpeaker.identity_confidence`
for the primary speaker and derives transcript/video status from
`(*_searched_at, child rows existence)`. The fixtures here exercise that path.
"""
from __future__ import annotations

import os
from datetime import datetime

import pytest


@pytest.fixture(scope="module")
def configured_db(tmp_path_factory):
    db_dir = tmp_path_factory.mktemp("dbcfg")
    db_path = db_dir / "test.sqlite"
    os.environ["DB_URL"] = f"sqlite:///{db_path}"
    os.environ["OBJECT_STORE_DIR"] = str(db_dir / "blobs")
    yield


def test_mode_filter_returns_only_pilot_initial(configured_db):
    from commencement.db.models import Control, Institution
    from commencement.db.session import get_session, init_schema
    from commencement.discovery.flow import _select_targets

    init_schema()
    with get_session() as session:
        session.add_all(
            [
                Institution(ipeds_id=1, name="A", control=Control.public, in_pilot=True),
                Institution(ipeds_id=2, name="B", control=Control.public, in_pilot=False),
                Institution(ipeds_id=3, name="C", control=Control.public, in_pilot=True),
            ]
        )

    ids = _select_targets("initial", None, 2026)
    assert set(ids) == {1, 3}


def test_mode_filter_catch_late(configured_db):
    """catch-late picks up ceremonies where the primary speaker has low
    confidence, OR transcript/video was searched-and-not-found."""
    from commencement.db.models import (
        Ceremony,
        CeremonySpeaker,
        CeremonyStatus,
        Control,
        IdentityMethod,
        Institution,
        Speaker,
        TranscriptKind,
        TranscriptLink,
        VideoLink,
        VideoPlatform,
    )
    from commencement.db.session import get_session, init_schema
    from commencement.discovery.flow import _select_targets

    init_schema()
    with get_session() as session:
        for inst in [
            Institution(ipeds_id=10, name="J", control=Control.public, in_pilot=True),
            Institution(ipeds_id=11, name="K", control=Control.public, in_pilot=True),
            Institution(ipeds_id=12, name="L", control=Control.public, in_pilot=True),
        ]:
            session.merge(inst)
        session.flush()

        spk_high = Speaker(normalized_name="high conf", display_name="High Conf")
        spk_low = Speaker(normalized_name="low conf", display_name="Low Conf")
        session.add_all([spk_high, spk_low])
        session.flush()

        # 10: past + transcript found + video found + high conf → NOT in catch-late
        c10 = Ceremony(
            ipeds_id=10, year=2026,
            ceremony_status=CeremonyStatus.past,
            transcript_searched_at=datetime.utcnow(),
            video_searched_at=datetime.utcnow(),
        )
        # 11: past + transcript searched-not-found + low-conf primary → IN catch-late
        c11 = Ceremony(
            ipeds_id=11, year=2026,
            ceremony_status=CeremonyStatus.past,
            transcript_searched_at=datetime.utcnow(),
            video_searched_at=datetime.utcnow(),
        )
        # 12: future → never in catch-late regardless of state
        c12 = Ceremony(
            ipeds_id=12, year=2026,
            ceremony_status=CeremonyStatus.future,
        )
        session.add_all([c10, c11, c12])
        session.flush()

        # 10 has a primary speaker with high confidence AND a transcript_link row
        session.add(CeremonySpeaker(
            ceremony_id=c10.ceremony_id, speaker_id=spk_high.speaker_id,
            is_primary=True, identity_method=IdentityMethod.official_press_release,
            identity_confidence=0.9,
        ))
        session.add(TranscriptLink(
            ceremony_id=c10.ceremony_id, source_tier=1,
            source_kind=TranscriptKind.institutional_html,
            url="https://example.edu/tx",
        ))
        session.add(VideoLink(
            ceremony_id=c10.ceremony_id, source_tier=1,
            platform=VideoPlatform.youtube,
            url="https://www.youtube.com/watch?v=test10",
        ))
        # 11 has a low-confidence primary, no transcript rows
        session.add(CeremonySpeaker(
            ceremony_id=c11.ceremony_id, speaker_id=spk_low.speaker_id,
            is_primary=True, identity_method=IdentityMethod.third_party_news,
            identity_confidence=0.4,
        ))

    ids = _select_targets("catch-late", None, 2026)
    assert 11 in ids, "low-confidence primary OR transcript-searched-no-rows should match"
    assert 10 not in ids, "high-conf primary with transcript row should NOT match"
    assert 12 not in ids, "future ceremonies are never in catch-late"


def test_mode_filter_institution_requires_id(configured_db):
    from commencement.discovery.flow import _select_targets

    with pytest.raises(ValueError):
        _select_targets("institution", None, 2026)
