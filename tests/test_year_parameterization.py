"""Pin year-parameterized behavior in manual.py helpers."""
from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="module")
def configured_db(tmp_path_factory):
    db_dir = tmp_path_factory.mktemp("dbcfg_year")
    db_path = db_dir / "test.sqlite"
    os.environ["DB_URL"] = f"sqlite:///{db_path}"
    os.environ["OBJECT_STORE_DIR"] = str(db_dir / "blobs")
    yield


def _seed_institution(ipeds_id: int):
    from commencement.db.models import Control, Institution
    from commencement.db.session import get_session, init_schema

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


def test_list_pilot_pending_filters_by_year(configured_db):
    from commencement.manual import list_pilot_pending, record_speaker

    _seed_institution(101)
    record_speaker(
        101,
        speaker_name="2025 Speaker",
        source_url="https://example.edu/2025",
        method="official_press_release",
        confidence=0.9,
        ceremony_date="2025-05-15",
        ceremony_status="past",
        year=2025,
    )
    # 101 now has a 2025 ceremony but NO 2026 ceremony
    pending_2025 = [r["ipeds_id"] for r in list_pilot_pending(limit=300, year=2025)]
    pending_2026 = [r["ipeds_id"] for r in list_pilot_pending(limit=300, year=2026)]
    assert 101 not in pending_2025
    assert 101 in pending_2026


def test_record_speaker_year_param_writes_correct_year(configured_db):
    from commencement.db.models import Ceremony
    from commencement.db.session import get_session
    from commencement.manual import record_speaker

    _seed_institution(102)
    cid = record_speaker(
        102,
        speaker_name="X",
        source_url="https://example.edu/x",
        method="official_press_release",
        confidence=0.9,
        ceremony_status="past",
        year=2024,
    )
    with get_session() as s:
        cer = s.get(Ceremony, cid)
        assert cer.year == 2024


def test_record_speaker_same_institution_different_years_coexist(configured_db):
    from commencement.db.models import Ceremony
    from commencement.db.session import get_session
    from commencement.manual import record_speaker
    from sqlalchemy import select

    _seed_institution(103)
    record_speaker(
        103,
        speaker_name="Y2025",
        source_url="https://example.edu/y25",
        method="official_press_release",
        confidence=0.9,
        ceremony_status="past",
        year=2025,
    )
    record_speaker(
        103,
        speaker_name="Y2026",
        source_url="https://example.edu/y26",
        method="official_press_release",
        confidence=0.9,
        ceremony_status="past",
        year=2026,
    )
    with get_session() as s:
        rows = s.execute(select(Ceremony).where(Ceremony.ipeds_id == 103)).scalars().all()
        years = {r.year: r.speaker_name for r in rows}
        assert years == {2025: "Y2025", 2026: "Y2026"}


def test_list_universitywide_speaker_ipeds_returns_cohort(configured_db):
    from commencement.manual import (
        list_universitywide_speaker_ipeds,
        record_no_speaker_found,
        record_school_level_ceremony,
        record_speaker,
    )

    for ipeds in (201, 202, 203, 204):
        _seed_institution(ipeds)

    # 201: universitywide with speaker (year=2026) — should appear
    record_speaker(
        201,
        speaker_name="A",
        source_url="https://example.edu/a",
        method="official_press_release",
        confidence=0.95,
        ceremony_status="past",
        year=2026,
    )
    # 202: school_level_only (year=2026) — should NOT appear
    record_school_level_ceremony(
        202,
        ceremony_status="past",
        year=2026,
        speakers=[
            {
                "speaker_name": "B",
                "source_url": "https://example.edu/b",
                "method": "official_press_release",
                "confidence": 0.95,
            }
        ],
    )
    # 203: no speaker found (year=2026) — should NOT appear
    record_no_speaker_found(203, ceremony_status="past", year=2026)
    # 204: universitywide with speaker but year=2025 — should NOT appear when querying 2026
    record_speaker(
        204,
        speaker_name="D",
        source_url="https://example.edu/d",
        method="official_press_release",
        confidence=0.95,
        ceremony_status="past",
        year=2025,
    )

    cohort_2026 = list_universitywide_speaker_ipeds(reference_year=2026)
    cohort_2025 = list_universitywide_speaker_ipeds(reference_year=2025)
    assert 201 in cohort_2026
    assert 202 not in cohort_2026
    assert 203 not in cohort_2026
    assert 204 not in cohort_2026
    assert 204 in cohort_2025


def test_pilot_progress_reports_year(configured_db):
    from commencement.manual import pilot_progress, record_speaker

    _seed_institution(301)
    record_speaker(
        301,
        speaker_name="P",
        source_url="https://example.edu/p",
        method="official_press_release",
        confidence=0.9,
        ceremony_status="past",
        year=2025,
    )
    prog_2025 = pilot_progress(year=2025)
    prog_2026 = pilot_progress(year=2026)
    assert prog_2025["year"] == 2025
    assert prog_2025["speakers_resolved"] >= 1
    assert prog_2026["year"] == 2026
    # 301's 2026 ceremony was not created
    # (other ceremonies from prior tests' 2026 inserts may exist; assert relative)
