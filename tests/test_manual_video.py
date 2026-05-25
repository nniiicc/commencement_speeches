"""Pin the behavior of the manual video-discovery helpers.

Uses the same module-scope env-var fixture pattern as test_mode_filters.py to
redirect DB_URL to a temp SQLite file. Passes in isolation; will fail alongside
other tests that import commencement.* at module top — that pollution issue is
documented and out of scope for this change.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="module")
def configured_db(tmp_path_factory):
    db_dir = tmp_path_factory.mktemp("dbcfg_video")
    db_path = db_dir / "test.sqlite"
    os.environ["DB_URL"] = f"sqlite:///{db_path}"
    os.environ["OBJECT_STORE_DIR"] = str(db_dir / "blobs")
    yield


def _seed_one_ceremony(ipeds_id: int = 1) -> int:
    """Insert an institution + a ceremony with a named speaker. Returns ceremony_id."""
    from commencement.db.models import Control, Institution
    from commencement.db.session import get_session, init_schema
    from commencement.manual import record_speaker

    init_schema()
    with get_session() as session:
        session.merge(
            Institution(
                ipeds_id=ipeds_id,
                name=f"Test Institution {ipeds_id}",
                control=Control.public,
                in_pilot=True,
            )
        )
    return record_speaker(
        ipeds_id,
        speaker_name="Jane Doe",
        source_url="https://example.edu/news/jane-doe",
        method="official_press_release",
        confidence=0.95,
        ceremony_date="2026-05-15",
        ceremony_status="past",
    )


def test_add_video_link_sets_status_and_returns_id(configured_db):
    from commencement.db.models import Ceremony, LinkStatus
    from commencement.db.session import get_session
    from commencement.manual import add_video_link

    cid = _seed_one_ceremony(ipeds_id=1)

    link_id = add_video_link(
        cid,
        url="https://www.youtube.com/watch?v=abc123",
        platform="youtube",
        tier=1,
        is_full_ceremony=True,
        duration_seconds=5400,
        published_at="2026-05-16",
    )
    assert link_id > 0

    with get_session() as s:
        cer = s.get(Ceremony, cid)
        assert cer.video_link_status == LinkStatus.found
        assert len(cer.video_links) == 1
        assert cer.video_links[0].url.endswith("abc123")
        assert cer.video_links[0].is_full_ceremony is True
        assert cer.video_links[0].duration_seconds == 5400


def test_add_video_link_dedupes_on_same_url(configured_db):
    from commencement.db.models import Ceremony
    from commencement.db.session import get_session
    from commencement.manual import add_video_link

    cid = _seed_one_ceremony(ipeds_id=2)
    url = "https://www.youtube.com/watch?v=dupe"

    id1 = add_video_link(cid, url=url, platform="youtube", tier=3)
    id2 = add_video_link(cid, url=url, platform="youtube", tier=3)
    assert id1 == id2

    with get_session() as s:
        cer = s.get(Ceremony, cid)
        assert len(cer.video_links) == 1


def test_add_video_link_allows_multiple_distinct_urls(configured_db):
    from commencement.db.models import Ceremony
    from commencement.db.session import get_session
    from commencement.manual import add_video_link

    cid = _seed_one_ceremony(ipeds_id=3)
    add_video_link(
        cid, url="https://www.youtube.com/watch?v=full", platform="youtube", tier=1
    )
    add_video_link(
        cid, url="https://www.c-span.org/video/?12345", platform="other", tier=2
    )
    with get_session() as s:
        cer = s.get(Ceremony, cid)
        assert len(cer.video_links) == 2


def test_add_video_link_rejects_bad_tier(configured_db):
    from commencement.manual import add_video_link

    cid = _seed_one_ceremony(ipeds_id=4)
    with pytest.raises(ValueError):
        add_video_link(cid, url="https://x", platform="youtube", tier=5)


def test_mark_video_not_found_sets_status(configured_db):
    from commencement.db.models import Ceremony, LinkStatus
    from commencement.db.session import get_session
    from commencement.manual import mark_video_not_found

    cid = _seed_one_ceremony(ipeds_id=5)
    mark_video_not_found(cid)
    with get_session() as s:
        cer = s.get(Ceremony, cid)
        assert cer.video_link_status == LinkStatus.not_found


def test_mark_video_not_found_raises_for_unknown_ceremony(configured_db):
    from commencement.manual import mark_video_not_found

    with pytest.raises(ValueError):
        mark_video_not_found(999_999)


def test_list_pending_for_video_excludes_already_found(configured_db):
    from commencement.manual import add_video_link, list_pending_for_video

    cid = _seed_one_ceremony(ipeds_id=6)
    # Before linking, it should appear in pending
    pending = list_pending_for_video()
    assert any(r["ceremony_id"] == cid for r in pending)

    # After linking, it should disappear
    add_video_link(cid, url="https://www.youtube.com/watch?v=found", platform="youtube")
    pending_after = list_pending_for_video()
    assert all(r["ceremony_id"] != cid for r in pending_after)


def test_list_pending_for_video_skips_future_by_default(configured_db):
    from commencement.manual import list_pending_for_video, record_speaker
    from commencement.db.models import Control, Institution
    from commencement.db.session import get_session

    with get_session() as session:
        session.merge(
            Institution(
                ipeds_id=7, name="Future Inst", control=Control.public, in_pilot=True
            )
        )
    cid = record_speaker(
        7,
        speaker_name="Future Speaker",
        source_url="https://example.edu/future",
        method="official_press_release",
        confidence=0.9,
        ceremony_date="2027-05-15",
        ceremony_status="future",
    )

    pending_default = list_pending_for_video()
    assert all(r["ceremony_id"] != cid for r in pending_default)

    pending_with_future = list_pending_for_video(include_future=True)
    assert any(r["ceremony_id"] == cid for r in pending_with_future)


def test_list_pending_for_video_child_count_for_school_level(configured_db):
    from commencement.db.models import Control, Institution
    from commencement.db.session import get_session
    from commencement.manual import (
        list_pending_for_video,
        record_school_level_ceremony,
    )

    with get_session() as session:
        session.merge(
            Institution(
                ipeds_id=8, name="Multi-school U", control=Control.public, in_pilot=True
            )
        )
    cid = record_school_level_ceremony(
        8,
        ceremony_status="past",
        ceremony_date="2026-05-09",
        speakers=[
            {
                "speaker_name": "Alpha",
                "school_or_college": "Law",
                "source_url": "https://example.edu/a",
                "method": "official_press_release",
                "confidence": 0.95,
            },
            {
                "speaker_name": "Beta",
                "school_or_college": "Medicine",
                "source_url": "https://example.edu/b",
                "method": "official_press_release",
                "confidence": 0.95,
            },
        ],
    )
    pending = list_pending_for_video()
    row = next(r for r in pending if r["ceremony_id"] == cid)
    assert row["ceremony_type"] == "school_level_only"
    assert row["child_speaker_count"] == 2
