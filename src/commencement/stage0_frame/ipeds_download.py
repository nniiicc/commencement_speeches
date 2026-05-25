"""Download the IPEDS HD zip, try most recent year first."""
from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from commencement.config import CONFIG

log = logging.getLogger(__name__)


class IpedsDownloadError(RuntimeError):
    pass


def download_hd_zip(years: Optional[tuple[int, ...]] = None) -> tuple[int, bytes]:
    candidates = years or CONFIG.IPEDS_HD_YEAR_CANDIDATES
    last_err: str | None = None
    for year in candidates:
        url = CONFIG.IPEDS_HD_URL_PATTERN.format(year=year)
        log.info("attempting IPEDS HD download: %s", url)
        try:
            resp = requests.get(
                url,
                timeout=CONFIG.HTTP_TIMEOUT_SECONDS,
                headers={"User-Agent": CONFIG.USER_AGENT},
            )
        except requests.RequestException as e:
            last_err = f"{url}: {e}"
            continue
        if resp.status_code == 200 and resp.content[:2] == b"PK":
            log.info("IPEDS HD%d downloaded (%d bytes)", year, len(resp.content))
            return year, resp.content
        last_err = f"{url}: HTTP {resp.status_code}"
    raise IpedsDownloadError(
        "Could not download IPEDS HD for any candidate year. "
        f"Last error: {last_err}. "
        "Provide a working URL via IPEDS_HD_URL_PATTERN or download manually."
    )


def extract_hd_csv(zip_bytes: bytes, year: int) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        candidates = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not candidates:
            raise IpedsDownloadError(f"No CSV found in HD{year}.zip; got {zf.namelist()}")
        prefer = [n for n in candidates if not n.lower().startswith("hd") or "_rv" in n.lower()]
        csv_name = prefer[0] if prefer else candidates[0]
        log.info("extracting %s from HD%d.zip", csv_name, year)
        with zf.open(csv_name) as f:
            df = pd.read_csv(f, encoding="latin-1", low_memory=False)
    df.columns = [c.lstrip("﻿").lstrip("\xef\xbb\xbf") for c in df.columns]
    return df


def fetch_hd_frame(years: Optional[tuple[int, ...]] = None) -> tuple[int, pd.DataFrame]:
    year, zip_bytes = download_hd_zip(years)
    df = extract_hd_csv(zip_bytes, year)
    cache_dir = Path("data/raw_ipeds")
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"HD{year}.zip").write_bytes(zip_bytes)
    return year, df
