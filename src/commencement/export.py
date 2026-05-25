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
  c.transcript_searched_at,
  c.video_searched_at,
  -- Primary speaker (universitywide keynote) joined in via ceremony_speakers
  -- + speakers. Three columns flatten the 3NF model back into the export row.
  ps.display_name        AS speaker_name,
  cs.source_url          AS identity_source_url,
  cs.identity_confidence,
  cs.identity_method,
  -- Tri-state flags derived from (searched_at, has_child_rows). Matches the
  -- pre-3NF column names so downstream consumers don't break.
  CASE
    WHEN c.transcript_searched_at IS NULL THEN 'not_searched'
    WHEN EXISTS (SELECT 1 FROM transcript_links tl WHERE tl.ceremony_id = c.ceremony_id) THEN 'found'
    ELSE 'not_found'
  END AS transcript_link_status,
  CASE
    WHEN c.video_searched_at IS NULL THEN 'not_searched'
    WHEN EXISTS (SELECT 1 FROM video_links vl WHERE vl.ceremony_id = c.ceremony_id) THEN 'found'
    ELSE 'not_found'
  END AS video_link_status,
  i.name AS institution_name,
  i.carnegie_classification,
  i.control,
  i.state,
  i.region,
  i.homepage_url
FROM ceremonies c
JOIN institutions i ON i.ipeds_id = c.ipeds_id
LEFT JOIN ceremony_speakers cs
  ON cs.ceremony_id = c.ceremony_id AND cs.is_primary = 1
LEFT JOIN speakers ps ON ps.speaker_id = cs.speaker_id
WHERE i.in_pilot = 1
  AND c.year = :year
"""


TRANSCRIPT_LINKS_QUERY = """
SELECT
  tl.transcript_link_id, tl.ceremony_id, c.ipeds_id,
  tl.source_tier, tl.source_kind, tl.url, tl.discovered_at, tl.verified_main_ceremony
FROM transcript_links tl
JOIN ceremonies c ON c.ceremony_id = tl.ceremony_id
"""


VIDEO_LINKS_QUERY = """
SELECT
  vl.video_link_id, vl.ceremony_id, c.ipeds_id,
  vl.platform, vl.url, vl.published_at, vl.duration_seconds, vl.is_full_ceremony, vl.discovered_at
FROM video_links vl
JOIN ceremonies c ON c.ceremony_id = vl.ceremony_id
"""


def export_corpus(
    version: int,
    out_dir: Path | None = None,
    year: int = CONFIG.PILOT_YEAR,
) -> dict[str, Path]:
    out_dir = Path(out_dir) if out_dir else CONFIG.EXPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    with engine.connect() as conn:
        ceremonies = pd.read_sql(CEREMONIES_QUERY, conn, params={"year": year})
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

    parquet_path = out_dir / f"commencements_{year}_discovery_v{version}.parquet"
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
