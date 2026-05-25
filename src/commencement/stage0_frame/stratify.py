"""Proportional-allocation stratified sample. Records the seed and per-stratum draw."""
from __future__ import annotations

import logging
from collections import Counter

import numpy as np
import pandas as pd
from sqlalchemy import update

from commencement.config import CONFIG
from commencement.db.models import Institution, PilotSampleLog
from commencement.db.session import get_session

log = logging.getLogger(__name__)


def _stratum_key(carnegie: str | None, control: str) -> str:
    return f"{carnegie or 'unknown'}|{control}"


def proportional_allocation(
    strata_sizes: dict[str, int], sample_size: int
) -> dict[str, int]:
    """Return per-stratum draw counts that sum to sample_size.

    Rounding remainder is distributed to the strata with the largest fractional parts,
    so the total equals sample_size exactly even when strata are small.
    """
    total = sum(strata_sizes.values())
    if total == 0:
        return {k: 0 for k in strata_sizes}
    raw = {k: sample_size * v / total for k, v in strata_sizes.items()}
    floor = {k: int(np.floor(x)) for k, x in raw.items()}
    remainder = sample_size - sum(floor.values())
    fractional = sorted(
        ((k, raw[k] - floor[k]) for k in raw), key=lambda kv: kv[1], reverse=True
    )
    out = dict(floor)
    for i in range(remainder):
        out[fractional[i % len(fractional)][0]] += 1
    return out


def draw_pilot_sample(
    sample_size: int = CONFIG.PILOT_SAMPLE_SIZE,
    seed: int = CONFIG.RANDOM_SEED,
) -> dict[str, int]:
    rng = np.random.default_rng(seed)

    with get_session() as session:
        rows = session.query(
            Institution.ipeds_id,
            Institution.carnegie_classification,
            Institution.control,
        ).all()
        df = pd.DataFrame(
            [
                {
                    "ipeds_id": r[0],
                    "carnegie": r[1],
                    "control": r[2].value if r[2] else "unknown",
                }
                for r in rows
            ]
        )
        if df.empty:
            raise RuntimeError("institutions table is empty; run Stage 0 frame load first")

        df["stratum"] = df.apply(
            lambda r: _stratum_key(r["carnegie"], r["control"]), axis=1
        )

        strata_sizes = df.groupby("stratum").size().to_dict()
        targets = proportional_allocation(strata_sizes, sample_size)

        drawn_ids: list[int] = []
        realized: dict[str, int] = {}
        for stratum, target in targets.items():
            candidates = df.loc[df["stratum"] == stratum, "ipeds_id"].to_numpy()
            if target <= 0 or len(candidates) == 0:
                realized[stratum] = 0
                continue
            n = min(target, len(candidates))
            picked = rng.choice(candidates, size=n, replace=False)
            drawn_ids.extend(picked.tolist())
            realized[stratum] = n

        log.info(
            "drew %d institutions across %d strata (seed=%d)",
            len(drawn_ids),
            len([v for v in realized.values() if v > 0]),
            seed,
        )

        session.execute(
            update(Institution).where(Institution.in_pilot.is_(True)).values(in_pilot=False)
        )
        session.execute(
            update(Institution)
            .where(Institution.ipeds_id.in_(drawn_ids))
            .values(in_pilot=True)
        )

        session.query(PilotSampleLog).filter(PilotSampleLog.seed == seed).delete()
        for stratum, target in targets.items():
            session.add(
                PilotSampleLog(
                    seed=seed,
                    stratum_key=stratum,
                    frame_size=strata_sizes.get(stratum, 0),
                    target_draw=target,
                    actual_draw=realized.get(stratum, 0),
                )
            )

    return realized
