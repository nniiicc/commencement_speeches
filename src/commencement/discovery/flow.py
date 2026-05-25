"""Prefect flow that walks pilot institutions and runs Steps 1->2->3.

Modes:
  initial       -- every pilot institution
  catch-late    -- only past ceremonies with both link statuses 'not_found' OR low identity confidence
  future        -- ceremony_status == 'future'
  institution   -- a single ipeds_id
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

from prefect import flow, get_run_logger, task
from sqlalchemy import and_, exists, or_, select

from commencement.config import CONFIG
from commencement.db.models import (
    Ceremony,
    CeremonySpeaker,
    CeremonyStatus,
    DiscoveryRun,
    Institution,
    TranscriptLink,
    VideoLink,
)
from commencement.db.session import get_session
from commencement.discovery.step1_speaker import resolve_speaker_for_institution
from commencement.discovery.step2_transcript_link import discover_transcript_links
from commencement.discovery.step3_video_link import discover_video_links
from commencement.search.tavily_provider import get_search_provider
from commencement.storage import BlobStore

log = logging.getLogger(__name__)


VALID_MODES = {"initial", "catch-late", "future", "institution"}


def _select_targets(mode: str, ipeds_id: int | None, year: int) -> list[int]:
    with get_session() as session:
        if mode == "institution":
            if ipeds_id is None:
                raise ValueError("--ipeds-id is required for --mode=institution")
            return [ipeds_id]

        base = session.query(Institution.ipeds_id).filter(Institution.in_pilot.is_(True))

        if mode == "initial":
            return [r[0] for r in base.all()]

        if mode == "future":
            stmt = (
                select(Institution.ipeds_id)
                .join(Ceremony, Ceremony.ipeds_id == Institution.ipeds_id)
                .where(
                    Institution.in_pilot.is_(True),
                    Ceremony.year == year,
                    Ceremony.ceremony_status == CeremonyStatus.future,
                )
            )
            return [r[0] for r in session.execute(stmt).all()]

        if mode == "catch-late":
            # Catch-late picks up past ceremonies where any of:
            #   - the primary speaker was identified with confidence < 0.5
            #   - we searched for a transcript and found none
            #     (transcript_searched_at IS NOT NULL AND no transcript_links rows)
            #   - same for video
            primary_low_conf = exists().where(
                and_(
                    CeremonySpeaker.ceremony_id == Ceremony.ceremony_id,
                    CeremonySpeaker.is_primary.is_(True),
                    CeremonySpeaker.identity_confidence < 0.5,
                )
            )
            transcript_not_found = and_(
                Ceremony.transcript_searched_at.is_not(None),
                ~exists().where(TranscriptLink.ceremony_id == Ceremony.ceremony_id),
            )
            video_not_found = and_(
                Ceremony.video_searched_at.is_not(None),
                ~exists().where(VideoLink.ceremony_id == Ceremony.ceremony_id),
            )
            stmt = (
                select(Institution.ipeds_id)
                .join(Ceremony, Ceremony.ipeds_id == Institution.ipeds_id)
                .where(
                    Institution.in_pilot.is_(True),
                    Ceremony.year == year,
                    Ceremony.ceremony_status == CeremonyStatus.past,
                    or_(primary_low_conf, transcript_not_found, video_not_found),
                )
            )
            return [r[0] for r in session.execute(stmt).all()]

        raise ValueError(f"unknown mode: {mode}")


def _load_institution(ipeds_id: int) -> Institution | None:
    with get_session() as session:
        inst = session.get(Institution, ipeds_id)
        if inst is None:
            return None
        session.expunge(inst)
        return inst


def _load_ceremony(ipeds_id: int, year: int) -> Ceremony | None:
    with get_session() as session:
        cer = (
            session.execute(
                select(Ceremony).where(
                    Ceremony.ipeds_id == ipeds_id, Ceremony.year == year
                )
            )
            .scalars()
            .first()
        )
        if cer is None:
            return None
        session.expunge(cer)
        return cer


@task(name="discover-institution")
def _discover_institution(ipeds_id: int, year: int) -> dict:
    inst = _load_institution(ipeds_id)
    if inst is None:
        return {"ipeds_id": ipeds_id, "status": "missing_institution"}

    provider = get_search_provider()
    blob_store = BlobStore()

    step1 = resolve_speaker_for_institution(inst, provider, blob_store, year=year)
    if step1.get("status") == "discarded_per_college":
        return step1

    cer = _load_ceremony(ipeds_id, year)
    if cer is None:
        return {"ipeds_id": ipeds_id, "status": "no_ceremony_after_step1"}

    step2 = discover_transcript_links(cer, inst, provider, year=year)
    step3 = discover_video_links(cer, inst, year=year)

    return {
        "ipeds_id": ipeds_id,
        "ceremony_id": cer.ceremony_id,
        "step1": step1,
        "step2": step2,
        "step3": step3,
    }


@flow(name="discovery")
def flow_discovery(
    mode: str = "initial",
    ipeds_id: int | None = None,
    triggered_by: str = "manual",
    year: int = CONFIG.PILOT_YEAR,
) -> dict:
    rlog = get_run_logger()
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {VALID_MODES}, got {mode}")

    targets = _select_targets(mode, ipeds_id, year)
    rlog.info("discovery mode=%s targets=%d", mode, len(targets))

    with get_session() as session:
        run = DiscoveryRun(
            triggered_by=triggered_by,
            mode=mode,
            pilot_size=len(targets),
            random_seed=CONFIG.RANDOM_SEED,
            started_at=datetime.utcnow(),
        )
        session.add(run)
        session.flush()
        run_id = run.run_id

    results: list[dict] = []
    for tid in targets:
        try:
            results.append(_discover_institution.fn(tid, year))
        except Exception as e:
            rlog.warning("discovery failed for ipeds_id=%d: %s", tid, e)
            results.append({"ipeds_id": tid, "status": "error", "error": str(e)})

    summary = {
        "n_total": len(results),
        "n_resolved_speaker": sum(
            1 for r in results if r.get("step1", {}).get("status") == "resolved"
        ),
        "n_transcript_links": sum(
            r.get("step2", {}).get("count", 0) or 0 for r in results
        ),
        "n_video_links": sum(r.get("step3", {}).get("count", 0) or 0 for r in results),
    }

    with get_session() as session:
        run = session.get(DiscoveryRun, run_id)
        run.ended_at = datetime.utcnow()
        run.summary_json = summary

    rlog.info("discovery run %d done: %s", run_id, summary)
    return {"run_id": run_id, **summary}
