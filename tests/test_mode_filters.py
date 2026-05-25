"""Verify the --mode filters return the right institutions.

These tests use an in-memory SQLite by pointing DB_URL elsewhere before import,
but here we set CONFIG to a temp file at module import time via env."""
from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture(scope="module")
def configured_db(tmp_path_factory):
    db_dir = tmp_path_factory.mktemp("dbcfg")
    db_path = db_dir / "test.sqlite"
    os.environ["DB_URL"] = f"sqlite:///{db_path}"
    os.environ["OBJECT_STORE_DIR"] = str(db_dir / "blobs")
    yield


def test_mode_filter_returns_only_pilot_initial(configured_db):
    from datetime import datetime

    from commencement.db.models import (
        Ceremony,
        CeremonyStatus,
        Control,
        Institution,
        LinkStatus,
    )
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

    ids = _select_targets("initial", None)
    assert set(ids) == {1, 3}


def test_mode_filter_catch_late(configured_db):
    from datetime import datetime

    from commencement.db.models import (
        Ceremony,
        CeremonyStatus,
        Control,
        Institution,
        LinkStatus,
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
        session.add_all(
            [
                Ceremony(
                    ipeds_id=10,
                    year=2026,
                    ceremony_status=CeremonyStatus.past,
                    transcript_link_status=LinkStatus.found,
                    video_link_status=LinkStatus.found,
                    identity_confidence=0.9,
                ),
                Ceremony(
                    ipeds_id=11,
                    year=2026,
                    ceremony_status=CeremonyStatus.past,
                    transcript_link_status=LinkStatus.not_found,
                    video_link_status=LinkStatus.not_found,
                    identity_confidence=0.4,
                ),
                Ceremony(
                    ipeds_id=12,
                    year=2026,
                    ceremony_status=CeremonyStatus.future,
                    transcript_link_status=LinkStatus.not_found,
                    video_link_status=LinkStatus.not_found,
                    identity_confidence=0.1,
                ),
            ]
        )

    ids = _select_targets("catch-late", None)
    assert 11 in ids
    assert 10 not in ids
    assert 12 not in ids


def test_mode_filter_institution_requires_id(configured_db):
    from commencement.discovery.flow import _select_targets

    import pytest

    with pytest.raises(ValueError):
        _select_targets("institution", None)
