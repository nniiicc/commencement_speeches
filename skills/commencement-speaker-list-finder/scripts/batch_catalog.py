"""Iterate an input CSV of institutions and write the catalog CSV.

Usage:
  python scripts/batch_catalog.py \
    --input examples/sample_institutions.csv \
    --output catalogs/speaker_lists_catalog.csv

Input CSV must have 'name' and 'homepage_url' columns; 'ipeds_id' optional.
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.probe_institution import CSV_COLUMNS, probe

log = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--limit", type=int, default=None, help="process only first N rows")
    args = p.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.input.open() as f_in:
        reader = csv.DictReader(f_in)
        institutions = list(reader)

    if args.limit:
        institutions = institutions[: args.limit]

    log.info("processing %d institutions", len(institutions))

    with args.output.open("w", newline="") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for i, row in enumerate(institutions, 1):
            name = row.get("name") or row.get("institution_name") or ""
            homepage = row.get("homepage_url") or row.get("homepage") or ""
            ipeds_id_raw = row.get("ipeds_id") or ""
            ipeds_id = int(ipeds_id_raw) if ipeds_id_raw.strip().isdigit() else None
            if not name or not homepage:
                log.warning("row %d missing name/homepage, skipping", i)
                continue
            log.info("[%d/%d] probing %s", i, len(institutions), name)
            try:
                for out_row in probe(name, homepage, ipeds_id):
                    writer.writerow(out_row)
            except Exception as e:
                log.exception("probe failed for %s: %s", name, e)
                writer.writerow({
                    **{c: "" for c in CSV_COLUMNS},
                    "ipeds_id": ipeds_id or "",
                    "institution_name": name,
                    "notes": f"error: {e}",
                })
            f_out.flush()

    log.info("wrote %s", args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
