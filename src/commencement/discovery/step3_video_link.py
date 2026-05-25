"""Step 3: video link discovery.

YouTube search via yt-dlp ytsearch (optionally YouTube Data API if a key is set).
Filter by channel match (if known), title heuristics, published date window,
and minimum duration. Records URL only; no audio download or transcription.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from pathlib import Path

import yaml
from sqlalchemy import select

from commencement.config import CONFIG
from commencement.db.models import (
    Ceremony,
    Institution,
    LinkStatus,
    VideoLink,
    VideoPlatform,
)
from commencement.db.session import get_session

log = logging.getLogger(__name__)


def _load_overrides(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def _ytdlp_search(query: str, n: int = 10) -> list[dict]:
    try:
        from yt_dlp import YoutubeDL
    except ImportError as e:
        raise RuntimeError("yt-dlp not installed") from e

    opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "noprogress": True,
    }
    with YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
        except Exception as e:
            log.warning("yt-dlp search failed for %r: %s", query, e)
            return []
    return info.get("entries", []) or []


def _parse_published(entry: dict) -> dt.datetime | None:
    val = entry.get("upload_date") or entry.get("release_date")
    if val and isinstance(val, str) and len(val) == 8:
        try:
            return dt.datetime.strptime(val, "%Y%m%d")
        except ValueError:
            return None
    ts = entry.get("timestamp")
    if isinstance(ts, (int, float)):
        return dt.datetime.utcfromtimestamp(ts)
    return None


_COMMENCEMENT_TITLE_RE = re.compile(r"\bcommencement\b", re.IGNORECASE)


def _channel_match(entry: dict, channel_url: str | None) -> bool:
    if not channel_url:
        return False
    cu = (entry.get("channel_url") or entry.get("uploader_url") or "").lower()
    return channel_url.lower().rstrip("/") in cu.rstrip("/")


def _looks_like_full_ceremony(entry: dict) -> bool | None:
    title = (entry.get("title") or "").lower()
    dur = entry.get("duration")
    if dur is None:
        return None
    if dur >= CONFIG.YOUTUBE_DURATION_MIN_SECONDS and "commencement" in title:
        return True
    if dur < 600:
        return False
    return None


def _within_date_window(published: dt.datetime | None, ceremony_date: dt.datetime | None) -> bool:
    if published is None or ceremony_date is None:
        return True
    delta = abs((published.date() - ceremony_date.date()).days)
    return delta <= CONFIG.YOUTUBE_DATE_WINDOW_DAYS


def _platform_from_url(url: str) -> VideoPlatform:
    u = url.lower()
    if "youtube.com" in u or "youtu.be" in u:
        return VideoPlatform.youtube
    if "vimeo.com" in u:
        return VideoPlatform.vimeo
    if "panopto" in u:
        return VideoPlatform.panopto
    if "kaltura" in u:
        return VideoPlatform.kaltura
    return VideoPlatform.other


def discover_video_links(
    ceremony: Ceremony,
    institution: Institution,
) -> dict:
    institution_name = institution.name
    channel_url = institution.youtube_channel_url
    overrides_yt = _load_overrides(CONFIG.OVERRIDES_YOUTUBE_CHANNELS)
    overrides_platforms = _load_overrides(CONFIG.OVERRIDES_VIDEO_PLATFORMS)

    if not channel_url and institution.ipeds_id in overrides_yt:
        channel_url = overrides_yt[institution.ipeds_id]

    query = f'"{institution_name}" commencement {CONFIG.PILOT_YEAR}'
    entries = _ytdlp_search(query, n=10)

    log.info(
        "step3: %d youtube candidates for %s (ceremony_id=%d)",
        len(entries),
        institution_name,
        ceremony.ceremony_id,
    )

    candidates: list[dict] = []
    for e in entries:
        url = e.get("url") or e.get("webpage_url") or ""
        if url and not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={url}"
        if not url:
            continue
        title = e.get("title") or ""
        if not (_COMMENCEMENT_TITLE_RE.search(title) and institution_name.lower().split(",")[0][:20] in title.lower()):
            if not _channel_match(e, channel_url):
                continue
        published = _parse_published(e)
        if not _within_date_window(published, ceremony.ceremony_date):
            continue
        dur = e.get("duration")
        candidates.append(
            {
                "url": url,
                "platform": VideoPlatform.youtube,
                "published_at": published,
                "duration_seconds": int(dur) if isinstance(dur, (int, float)) else None,
                "is_full_ceremony": _looks_like_full_ceremony(e),
                "channel_match": _channel_match(e, channel_url),
            }
        )

    candidates.sort(
        key=lambda c: (
            c["channel_match"] is True,
            c["is_full_ceremony"] is True,
            (c["duration_seconds"] or 0),
        ),
        reverse=True,
    )

    institution_platform_override = overrides_platforms.get(institution.ipeds_id)
    if institution_platform_override:
        candidates.append(
            {
                "url": institution_platform_override.get("url", ""),
                "platform": _platform_from_url(institution_platform_override.get("url", "")),
                "published_at": None,
                "duration_seconds": None,
                "is_full_ceremony": None,
                "channel_match": False,
            }
        )

    with get_session() as session:
        existing_urls = {
            r[0]
            for r in session.execute(
                select(VideoLink.url).where(VideoLink.ceremony_id == ceremony.ceremony_id)
            ).all()
        }
        for c in candidates:
            if not c["url"] or c["url"] in existing_urls:
                continue
            session.add(
                VideoLink(
                    ceremony_id=ceremony.ceremony_id,
                    ipeds_id=ceremony.ipeds_id,
                    source_tier=3,
                    platform=c["platform"],
                    url=c["url"],
                    published_at=c["published_at"],
                    duration_seconds=c["duration_seconds"],
                    is_full_ceremony=c["is_full_ceremony"],
                )
            )

        cer = session.get(Ceremony, ceremony.ceremony_id)
        cer.video_link_status = (
            LinkStatus.found if candidates else LinkStatus.not_found
        )

        if not institution.youtube_channel_url and candidates:
            best = candidates[0]
            if best.get("channel_match"):
                inst = session.get(Institution, institution.ipeds_id)
                inst.youtube_channel_url = channel_url

    return {
        "ceremony_id": ceremony.ceremony_id,
        "status": "found" if candidates else "not_found",
        "count": len(candidates),
    }
