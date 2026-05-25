"""One-shot in-place migration: corpus schema → 3NF.

Idempotent. Safe to re-run; each step checks current schema state via
PRAGMA table_info before mutating.

Changes:

1. `speakers` table — recreated keyed by `normalized_name` (was coupled to
   `ipeds_id`). Speaker is a person, not bound to a school.
2. `ceremony_speakers` — gains `speaker_id` FK + `is_primary` bool.
   Loses `speaker_name` (now via `speaker_id → speakers.display_name`).
3. `ceremonies` — gains `transcript_searched_at` / `video_searched_at`
   timestamps (replaces the cached enum statuses). Loses `speaker_name`,
   `identity_source_url`, `identity_confidence`, `identity_method`,
   `transcript_link_status`, `video_link_status` (now derivable via
   `ceremony_speakers` and the link tables).
4. `transcript_links` / `video_links` — lose `ipeds_id` (transitive via
   `ceremony_id → ceremonies.ipeds_id`).
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import text

from commencement.common.normalize import normalize_name
from commencement.db.session import engine

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _columns(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {r[1] for r in rows}


def step_a_add_columns(conn) -> None:
    """Additive ALTER TABLEs — safe on SQLite 3.35+."""
    cs_cols = _columns(conn, "ceremony_speakers")
    if "speaker_id" not in cs_cols:
        conn.execute(text(
            "ALTER TABLE ceremony_speakers ADD COLUMN speaker_id INTEGER "
            "REFERENCES speakers(speaker_id)"
        ))
        log.info("added ceremony_speakers.speaker_id")
    if "is_primary" not in cs_cols:
        conn.execute(text(
            "ALTER TABLE ceremony_speakers ADD COLUMN is_primary BOOLEAN "
            "NOT NULL DEFAULT 0"
        ))
        log.info("added ceremony_speakers.is_primary")

    c_cols = _columns(conn, "ceremonies")
    if "transcript_searched_at" not in c_cols:
        conn.execute(text(
            "ALTER TABLE ceremonies ADD COLUMN transcript_searched_at DATETIME"
        ))
        log.info("added ceremonies.transcript_searched_at")
    if "video_searched_at" not in c_cols:
        conn.execute(text(
            "ALTER TABLE ceremonies ADD COLUMN video_searched_at DATETIME"
        ))
        log.info("added ceremonies.video_searched_at")


def step_b_recreate_speakers(conn) -> None:
    """Drop old `speakers` (empty in this DB) and create the new shape."""
    n = conn.execute(text("SELECT COUNT(*) FROM speakers")).scalar()
    if n != 0:
        raise RuntimeError(
            f"speakers table not empty ({n} rows); migration aborted to avoid data loss"
        )
    conn.execute(text("DROP TABLE IF EXISTS speakers"))
    conn.execute(text("""
        CREATE TABLE speakers (
            speaker_id INTEGER PRIMARY KEY AUTOINCREMENT,
            normalized_name VARCHAR(256) NOT NULL UNIQUE,
            display_name VARCHAR(256) NOT NULL,
            speaker_role VARCHAR(512),
            affiliation VARCHAR(512),
            bio_url VARCHAR(1024),
            wikidata_qid VARCHAR(32),
            first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text(
        "CREATE INDEX ix_speakers_normalized_name ON speakers(normalized_name)"
    ))
    log.info("recreated speakers table (keyed by normalized_name)")


def step_c_backfill_speakers(conn) -> None:
    """One Speaker row per distinct normalized_name from ceremonies + ceremony_speakers."""
    seen: dict[str, str] = {}
    rows = conn.execute(text(
        "SELECT speaker_name FROM ceremonies WHERE speaker_name IS NOT NULL"
    )).fetchall()
    for (name,) in rows:
        norm = normalize_name(name)
        seen.setdefault(norm, name)

    rows = conn.execute(text(
        "SELECT speaker_name FROM ceremony_speakers WHERE speaker_name IS NOT NULL"
    )).fetchall()
    for (name,) in rows:
        norm = normalize_name(name)
        seen.setdefault(norm, name)

    for norm, display in seen.items():
        conn.execute(
            text("INSERT INTO speakers (normalized_name, display_name) VALUES (:n, :d)"),
            {"n": norm, "d": display},
        )
    log.info("backfilled %d speakers", len(seen))


def step_d_insert_primary_ceremony_speakers(conn) -> None:
    """For each Ceremony with a universitywide speaker_name, insert a
    CeremonySpeaker row marked is_primary=True. Copies the identity_*
    columns onto the row."""
    rows = conn.execute(text("""
        SELECT c.ceremony_id, c.speaker_name, c.identity_source_url,
               c.identity_method, c.identity_confidence, c.notes, c.last_discovery_run_at
        FROM ceremonies c
        WHERE c.speaker_name IS NOT NULL
    """)).fetchall()
    inserted = 0
    for r in rows:
        norm = normalize_name(r.speaker_name)
        speaker_id = conn.execute(
            text("SELECT speaker_id FROM speakers WHERE normalized_name = :n"),
            {"n": norm},
        ).scalar()
        if speaker_id is None:
            raise RuntimeError(f"missing speaker for {r.speaker_name!r}")
        # Skip if a row already exists for (ceremony_id, speaker_id) — idempotent
        existing = conn.execute(text("""
            SELECT id FROM ceremony_speakers
            WHERE ceremony_id = :c AND speaker_id = :s
        """), {"c": r.ceremony_id, "s": speaker_id}).scalar()
        if existing is not None:
            # already linked (e.g., school-level case where the primary name
            # was also recorded as the first school_speaker) — flip its flag
            conn.execute(text(
                "UPDATE ceremony_speakers SET is_primary = 1 WHERE id = :i"
            ), {"i": existing})
            continue
        conn.execute(text("""
            INSERT INTO ceremony_speakers
                (ceremony_id, speaker_id, speaker_name, is_primary,
                 source_url, identity_method, identity_confidence, notes,
                 discovered_at)
            VALUES (:c, :s, :n, 1, :url, :m, :conf, :notes, :ts)
        """), {
            "c": r.ceremony_id, "s": speaker_id, "n": r.speaker_name,
            "url": r.identity_source_url, "m": r.identity_method,
            "conf": r.identity_confidence, "notes": r.notes,
            "ts": r.last_discovery_run_at or datetime.utcnow(),
        })
        inserted += 1
    log.info("inserted %d primary ceremony_speakers rows", inserted)


def step_e_link_existing_ceremony_speakers(conn) -> None:
    """Populate speaker_id on pre-existing ceremony_speakers rows by
    normalized_name lookup. (These rows were created for school-level
    ceremonies; they have speaker_name but speaker_id is null.)"""
    rows = conn.execute(text("""
        SELECT id, speaker_name FROM ceremony_speakers WHERE speaker_id IS NULL
    """)).fetchall()
    for r in rows:
        norm = normalize_name(r.speaker_name)
        sid = conn.execute(
            text("SELECT speaker_id FROM speakers WHERE normalized_name = :n"),
            {"n": norm},
        ).scalar()
        if sid is None:
            raise RuntimeError(f"missing speaker for {r.speaker_name!r}")
        conn.execute(
            text("UPDATE ceremony_speakers SET speaker_id = :s WHERE id = :i"),
            {"s": sid, "i": r.id},
        )
    log.info("linked %d existing ceremony_speakers to speakers", len(rows))


def step_f_backfill_searched_at(conn) -> None:
    """Convert the cached `*_link_status` enums to `*_searched_at` timestamps.
    `not_searched` → NULL. `found` or `not_found` → ceremony.last_discovery_run_at
    (or NOW() if that's null)."""
    conn.execute(text("""
        UPDATE ceremonies
        SET transcript_searched_at = COALESCE(last_discovery_run_at, CURRENT_TIMESTAMP)
        WHERE transcript_link_status IN ('found', 'not_found')
    """))
    conn.execute(text("""
        UPDATE ceremonies
        SET video_searched_at = COALESCE(last_discovery_run_at, CURRENT_TIMESTAMP)
        WHERE video_link_status IN ('found', 'not_found')
    """))
    log.info("backfilled transcript_searched_at / video_searched_at")


def step_g_drop_old_columns(conn) -> None:
    """Drop denormalized columns. Requires SQLite 3.35+.

    SQLite rejects DROP COLUMN if a non-trivial index references the column,
    so we drop matching indexes first.
    """
    drops = [
        ("ceremonies", "speaker_name", []),
        ("ceremonies", "identity_source_url", []),
        ("ceremonies", "identity_confidence", []),
        ("ceremonies", "identity_method", []),
        ("ceremonies", "transcript_link_status", []),
        ("ceremonies", "video_link_status", []),
        ("ceremony_speakers", "speaker_name", []),
        ("transcript_links", "ipeds_id", ["ix_transcript_links_ipeds_id"]),
        ("video_links", "ipeds_id", ["ix_video_links_ipeds_id"]),
    ]
    for table, col, indexes_to_drop in drops:
        if col in _columns(conn, table):
            for idx in indexes_to_drop:
                conn.execute(text(f"DROP INDEX IF EXISTS {idx}"))
            conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {col}"))
            log.info("dropped %s.%s", table, col)


def step_h_constraints(conn) -> None:
    """Add a unique index (ceremony_id, speaker_id) on ceremony_speakers to
    enforce one row per (ceremony, person) pair."""
    existing = conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND name='uq_ceremony_speaker'"
    )).scalar()
    if existing is None:
        conn.execute(text(
            "CREATE UNIQUE INDEX uq_ceremony_speaker "
            "ON ceremony_speakers(ceremony_id, speaker_id)"
        ))
        log.info("created unique index uq_ceremony_speaker")


def verify(conn) -> None:
    n_speakers = conn.execute(text("SELECT COUNT(*) FROM speakers")).scalar()
    n_cs = conn.execute(text("SELECT COUNT(*) FROM ceremony_speakers")).scalar()
    n_primary = conn.execute(text(
        "SELECT COUNT(*) FROM ceremony_speakers WHERE is_primary = 1"
    )).scalar()
    n_cer = conn.execute(text("SELECT COUNT(*) FROM ceremonies")).scalar()
    n_cer_with_speaker = conn.execute(text("""
        SELECT COUNT(DISTINCT ceremony_id) FROM ceremony_speakers
    """)).scalar()
    log.info("==== POST-MIGRATION ====")
    log.info("speakers: %d", n_speakers)
    log.info("ceremony_speakers: %d (primary=%d)", n_cs, n_primary)
    log.info("ceremonies: %d (with at least one speaker=%d)", n_cer, n_cer_with_speaker)

    # Spot-check: same person across institutions should be ONE speaker row
    rows = conn.execute(text("""
        SELECT s.display_name, COUNT(DISTINCT c.ipeds_id) AS n_inst
        FROM speakers s
        JOIN ceremony_speakers cs ON cs.speaker_id = s.speaker_id
        JOIN ceremonies c ON c.ceremony_id = cs.ceremony_id
        GROUP BY s.speaker_id
        HAVING n_inst > 1
        ORDER BY n_inst DESC
    """)).fetchall()
    if rows:
        log.info("speakers appearing at >1 institutions:")
        for r in rows[:10]:
            log.info("  %s — %d institutions", r.display_name, r.n_inst)


def main() -> None:
    with engine.begin() as conn:
        step_a_add_columns(conn)
        step_b_recreate_speakers(conn)
        step_c_backfill_speakers(conn)
        # E before D: existing ceremony_speakers rows must have speaker_id
        # populated before step_d tries to dedupe against them.
        step_e_link_existing_ceremony_speakers(conn)
        step_d_insert_primary_ceremony_speakers(conn)
        step_f_backfill_searched_at(conn)
        step_g_drop_old_columns(conn)
        step_h_constraints(conn)
        verify(conn)


if __name__ == "__main__":
    main()
