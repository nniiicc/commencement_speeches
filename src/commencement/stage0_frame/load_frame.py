"""Filter the IPEDS HD CSV to active, degree-granting, Title IV institutions and insert."""
from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd
from sqlalchemy import delete

from commencement.common.normalize import state_to_region
from commencement.db.models import Control, Institution
from commencement.db.session import get_session, init_schema

log = logging.getLogger(__name__)


CONTROL_MAP = {
    1: Control.public,
    2: Control.private_nonprofit,
    3: Control.for_profit,
}


def _pick_col(df: pd.DataFrame, *candidates: str) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def filter_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Active + degree-granting + Title IV.

    Column names vary slightly across IPEDS HD vintages so we look up several candidates.
    """
    df = df.copy()

    act_col = _pick_col(df, "ACT", "ACTCAT")
    if act_col is not None:
        df = df[df[act_col].astype(str).str.upper().isin({"A", "1"})]

    opeflag_col = _pick_col(df, "OPEFLAG")
    if opeflag_col is not None:
        df = df[df[opeflag_col].isin([1, 2, 3])]

    iclevel_col = _pick_col(df, "ICLEVEL")
    if iclevel_col is not None:
        df = df[df[iclevel_col].isin([1, 2])]

    sector_col = _pick_col(df, "SECTOR")
    if sector_col is not None:
        df = df[df[sector_col].isin([1, 2, 3, 4, 5, 6])]

    return df


def to_institution_rows(df: pd.DataFrame, frame_year: int) -> list[dict]:
    name_col = _pick_col(df, "INSTNM", "Institution Name")
    state_col = _pick_col(df, "STABBR", "STATE")
    control_col = _pick_col(df, "CONTROL")
    carnegie_col = _pick_col(df, "C21BASIC", "C18BASIC", "C15BASIC", "CARNEGIE")
    web_col = _pick_col(df, "WEBADDR", "WEBURL")

    rows = []
    for _, r in df.iterrows():
        try:
            ipeds_id = int(r["UNITID"])
        except (KeyError, ValueError, TypeError):
            continue

        control_val = r[control_col] if control_col else None
        try:
            control_enum = CONTROL_MAP.get(int(control_val), Control.unknown)
        except (TypeError, ValueError):
            control_enum = Control.unknown

        state = str(r[state_col]).upper() if state_col and pd.notna(r[state_col]) else None
        homepage = r[web_col] if web_col and pd.notna(r[web_col]) else None
        if homepage and not str(homepage).startswith(("http://", "https://")):
            homepage = "http://" + str(homepage).strip()

        carnegie = (
            str(r[carnegie_col]) if carnegie_col and pd.notna(r[carnegie_col]) else None
        )

        rows.append(
            {
                "ipeds_id": ipeds_id,
                "name": str(r[name_col]) if name_col else "",
                "carnegie_classification": carnegie,
                "control": control_enum,
                "state": state,
                "region": state_to_region(state),
                "homepage_url": homepage,
                "in_pilot": False,
                "frame_year": frame_year,
                "loaded_at": datetime.utcnow(),
            }
        )
    return rows


def load_institutions(df: pd.DataFrame, frame_year: int, reload: bool = False) -> int:
    init_schema()
    rows = to_institution_rows(filter_frame(df), frame_year)
    log.info("preparing %d institution rows for insert", len(rows))

    with get_session() as session:
        if reload:
            session.execute(delete(Institution))
        existing_ids = {r[0] for r in session.query(Institution.ipeds_id).all()}
        new_rows = [r for r in rows if r["ipeds_id"] not in existing_ids]
        if new_rows:
            session.bulk_insert_mappings(Institution, new_rows)
        log.info("inserted %d new institutions (skipped %d already present)",
                 len(new_rows), len(rows) - len(new_rows))
    return len(rows)
