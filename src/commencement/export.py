"""Versioned exports: ceremonies joined to links + coverage-by-stratum csv."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from commencement.config import CONFIG
from commencement.db.session import engine

log = logging.getLogger(__name__)


CEREMONIES_QUERY = """
SELECT
  c.ceremony_id,
  c.ipeds_id,
  c.year,
  c.ceremony_date,
  c.ceremony_status,
  c.ceremony_type,
  c.speaker_name,
  c.identity_source_url,
  c.identity_confidence,
  c.identity_method,
  c.transcript_link_status,
  c.video_link_status,
  i.name AS institution_name,
  i.carnegie_classification,
  i.control,
  i.state,
  i.region,
  i.homepage_url
FROM ceremonies c
JOIN institutions i ON i.ipeds_id = c.ipeds_id
WHERE i.in_pilot = 1
"""


TRANSCRIPT_LINKS_QUERY = """
SELECT
  ceremony_id, ipeds_id, source_tier, source_kind, url, discovered_at, verified_main_ceremony
FROM transcript_links
"""


VIDEO_LINKS_QUERY = """
SELECT
  ceremony_id, ipeds_id, platform, url, published_at, duration_seconds, is_full_ceremony, discovered_at
FROM video_links
"""


def export_corpus(version: int, out_dir: Path | None = None) -> dict[str, Path]:
    out_dir = Path(out_dir) if out_dir else CONFIG.EXPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    with engine.connect() as conn:
        ceremonies = pd.read_sql(CEREMONIES_QUERY, conn)
        transcripts = pd.read_sql(TRANSCRIPT_LINKS_QUERY, conn)
        videos = pd.read_sql(VIDEO_LINKS_QUERY, conn)

    transcript_lists = (
        transcripts.groupby("ceremony_id")
        .apply(lambda g: g[["source_tier", "source_kind", "url"]].to_dict("records"))
        .rename("transcript_links")
        .reset_index()
    )
    video_lists = (
        videos.groupby("ceremony_id")
        .apply(lambda g: g[["platform", "url", "duration_seconds", "is_full_ceremony"]].to_dict("records"))
        .rename("video_links")
        .reset_index()
    )

    merged = ceremonies.merge(transcript_lists, on="ceremony_id", how="left")
    merged = merged.merge(video_lists, on="ceremony_id", how="left")

    parquet_path = out_dir / f"commencements_{CONFIG.PILOT_YEAR}_discovery_v{version}.parquet"
    merged.to_parquet(parquet_path, index=False)
    log.info("wrote %s (%d rows)", parquet_path, len(merged))

    coverage = (
        merged.groupby(["carnegie_classification", "control"])
        .agg(
            n=("ceremony_id", "count"),
            n_speaker_resolved=("speaker_name", lambda s: s.notna().sum()),
            n_transcript_found=(
                "transcript_link_status",
                lambda s: (s == "found").sum(),
            ),
            n_video_found=("video_link_status", lambda s: (s == "found").sum()),
        )
        .reset_index()
    )
    csv_path = out_dir / f"coverage_by_stratum_v{version}.csv"
    coverage.to_csv(csv_path, index=False)
    log.info("wrote %s", csv_path)

    return {"parquet": parquet_path, "coverage_csv": csv_path}
