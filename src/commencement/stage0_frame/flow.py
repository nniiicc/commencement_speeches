"""Prefect flow for Stage 0 (frame construction)."""
from __future__ import annotations

import logging

from prefect import flow, task

from commencement.config import CONFIG
from commencement.stage0_frame.ipeds_download import fetch_hd_frame
from commencement.stage0_frame.load_frame import load_institutions
from commencement.stage0_frame.stratify import draw_pilot_sample

log = logging.getLogger(__name__)


@task(name="fetch-and-load-hd")
def _fetch_and_load(reload: bool) -> int:
    year, df = fetch_hd_frame()
    return load_institutions(df, frame_year=year, reload=reload)


@task(name="stratified-sample")
def _stratify(sample_size: int, seed: int) -> dict[str, int]:
    return draw_pilot_sample(sample_size=sample_size, seed=seed)


@flow(name="frame-construction")
def flow_frame_construction(
    reload: bool = False,
    sample_size: int = CONFIG.PILOT_SAMPLE_SIZE,
    seed: int = CONFIG.RANDOM_SEED,
) -> dict:
    inserted = _fetch_and_load(reload)
    realized = _stratify(sample_size, seed)
    return {"institutions_loaded": inserted, "per_stratum_draw": realized}
