"""Single source of truth for tunable parameters. Nothing tunable lives elsewhere."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name)
    return val if val not in (None, "") else default


@dataclass(frozen=True)
class Config:
    PILOT_SAMPLE_SIZE: int = 300
    RANDOM_SEED: int = 20260524

    PILOT_YEAR: int = 2026

    IPEDS_HD_URL_PATTERN: str = "https://nces.ed.gov/ipeds/datacenter/data/HD{year}.zip"
    IPEDS_HD_YEAR_CANDIDATES: tuple[int, ...] = (2024, 2023, 2022)

    RATE_LIMIT_PER_DOMAIN: float = 1.0
    HTTP_TIMEOUT_SECONDS: int = 30
    HTTP_MAX_RETRIES: int = 3
    USER_AGENT: str = field(
        default_factory=lambda: _env(
            "USER_AGENT",
            "commencement-corpus-bot/0.1 (contact: nicholas.m.weber@gmail.com)",
        )
    )

    DB_URL: str = field(
        default_factory=lambda: _env("DB_URL", "sqlite:///data/corpus.sqlite")
    )
    OBJECT_STORE_DIR: Path = field(
        default_factory=lambda: Path(_env("OBJECT_STORE_DIR", "data/blobs/"))
    )

    WEB_SEARCH_PROVIDER: str = "tavily"
    LLM_MODEL_EXTRACTION: str = "claude-haiku-4-5"
    LLM_MODEL_HARD_PAGES: str = "claude-sonnet-4-6"

    YOUTUBE_DURATION_MIN_SECONDS: int = 1800
    YOUTUBE_DATE_WINDOW_DAYS: int = 30
    CSPAN_DATE_WINDOW_DAYS: int = 14

    ANTHROPIC_API_KEY: str | None = field(
        default_factory=lambda: _env("ANTHROPIC_API_KEY")
    )
    TAVILY_API_KEY: str | None = field(default_factory=lambda: _env("TAVILY_API_KEY"))
    YOUTUBE_API_KEY: str | None = field(default_factory=lambda: _env("YOUTUBE_API_KEY"))

    EXPORTS_DIR: Path = Path("exports/")

    OVERRIDES_YOUTUBE_CHANNELS: Path = Path("overrides/youtube_channels.yaml")
    OVERRIDES_VIDEO_PLATFORMS: Path = Path("overrides/video_platforms.yaml")


CONFIG = Config()
