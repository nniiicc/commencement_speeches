"""SQLAlchemy models matching the schema in the design doc."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Control(str, enum.Enum):
    public = "public"
    private_nonprofit = "private_nonprofit"
    for_profit = "for_profit"
    unknown = "unknown"


class CeremonyStatus(str, enum.Enum):
    past = "past"
    future = "future"
    unknown = "unknown"


class CeremonyType(str, enum.Enum):
    universitywide = "universitywide"
    school_level_only = "school_level_only"
    unknown = "unknown"


class IdentityMethod(str, enum.Enum):
    official_press_release = "official_press_release"
    institutional_news = "institutional_news"
    third_party_news = "third_party_news"
    none = "none"


class LinkStatus(str, enum.Enum):
    found = "found"
    not_found = "not_found"
    not_searched = "not_searched"


class TranscriptKind(str, enum.Enum):
    institutional_html = "institutional_html"
    cspan_caption = "cspan_caption"
    cspan_page = "cspan_page"
    pdf = "pdf"
    other = "other"


class VideoPlatform(str, enum.Enum):
    youtube = "youtube"
    vimeo = "vimeo"
    panopto = "panopto"
    kaltura = "kaltura"
    institutional_player = "institutional_player"
    livestream_archive = "livestream_archive"
    other = "other"


class SourceKind(str, enum.Enum):
    html = "html"
    json = "json"
    pdf = "pdf"
    image = "image"


class Institution(Base):
    __tablename__ = "institutions"

    ipeds_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(512))
    carnegie_classification: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    control: Mapped[Control] = mapped_column(Enum(Control), index=True)
    state: Mapped[Optional[str]] = mapped_column(String(8), index=True)
    region: Mapped[Optional[str]] = mapped_column(String(32))
    homepage_url: Mapped[Optional[str]] = mapped_column(String(512))
    news_url: Mapped[Optional[str]] = mapped_column(String(512))
    youtube_channel_url: Mapped[Optional[str]] = mapped_column(String(512))
    in_pilot: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    frame_year: Mapped[Optional[int]] = mapped_column(Integer)
    loaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    ceremonies: Mapped[list["Ceremony"]] = relationship(back_populates="institution")


class Ceremony(Base):
    __tablename__ = "ceremonies"
    __table_args__ = (UniqueConstraint("ipeds_id", "year", name="uq_ceremony_inst_year"),)

    ceremony_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ipeds_id: Mapped[int] = mapped_column(ForeignKey("institutions.ipeds_id"), index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    ceremony_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    ceremony_status: Mapped[CeremonyStatus] = mapped_column(
        Enum(CeremonyStatus), default=CeremonyStatus.unknown, index=True
    )
    ceremony_type: Mapped[CeremonyType] = mapped_column(
        Enum(CeremonyType), default=CeremonyType.unknown
    )
    speaker_name: Mapped[Optional[str]] = mapped_column(String(256))
    identity_source_url: Mapped[Optional[str]] = mapped_column(String(1024))
    identity_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    identity_method: Mapped[IdentityMethod] = mapped_column(
        Enum(IdentityMethod), default=IdentityMethod.none
    )
    transcript_link_status: Mapped[LinkStatus] = mapped_column(
        Enum(LinkStatus), default=LinkStatus.not_searched
    )
    video_link_status: Mapped[LinkStatus] = mapped_column(
        Enum(LinkStatus), default=LinkStatus.not_searched
    )
    last_discovery_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    institution: Mapped[Institution] = relationship(back_populates="ceremonies")
    transcript_links: Mapped[list["TranscriptLink"]] = relationship(
        back_populates="ceremony", cascade="all, delete-orphan"
    )
    video_links: Mapped[list["VideoLink"]] = relationship(
        back_populates="ceremony", cascade="all, delete-orphan"
    )
    school_speakers: Mapped[list["CeremonySpeaker"]] = relationship(
        back_populates="ceremony", cascade="all, delete-orphan"
    )


class CeremonySpeaker(Base):
    """One row per named speaker when a ceremony has multiple school-level speakers.

    Used when `Ceremony.ceremony_type == school_level_only`. Each row records who
    spoke at which sub-ceremony (school/college name + ceremony label).
    """

    __tablename__ = "ceremony_speakers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ceremony_id: Mapped[int] = mapped_column(
        ForeignKey("ceremonies.ceremony_id"), index=True
    )
    speaker_name: Mapped[str] = mapped_column(String(256))
    school_or_college: Mapped[Optional[str]] = mapped_column(String(256))
    ceremony_label: Mapped[Optional[str]] = mapped_column(String(256))
    source_url: Mapped[Optional[str]] = mapped_column(String(1024))
    identity_method: Mapped[IdentityMethod] = mapped_column(
        Enum(IdentityMethod), default=IdentityMethod.none
    )
    identity_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    ceremony: Mapped[Ceremony] = relationship(back_populates="school_speakers")


class Speaker(Base):
    __tablename__ = "speakers"
    __table_args__ = (
        UniqueConstraint("normalized_name", "ipeds_id", name="uq_speaker_inst"),
    )

    speaker_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    speaker_name: Mapped[str] = mapped_column(String(256))
    normalized_name: Mapped[str] = mapped_column(String(256), index=True)
    speaker_role: Mapped[Optional[str]] = mapped_column(String(512))
    affiliation: Mapped[Optional[str]] = mapped_column(String(512))
    bio_url: Mapped[Optional[str]] = mapped_column(String(1024))
    wikidata_qid: Mapped[Optional[str]] = mapped_column(String(32))
    ipeds_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("institutions.ipeds_id"), index=True
    )


class TranscriptLink(Base):
    __tablename__ = "transcript_links"

    transcript_link_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    ceremony_id: Mapped[int] = mapped_column(ForeignKey("ceremonies.ceremony_id"), index=True)
    ipeds_id: Mapped[int] = mapped_column(Integer, index=True)
    source_tier: Mapped[int] = mapped_column(Integer)
    source_kind: Mapped[TranscriptKind] = mapped_column(Enum(TranscriptKind))
    url: Mapped[str] = mapped_column(String(1024))
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    content_hash: Mapped[Optional[str]] = mapped_column(
        ForeignKey("sources.content_hash"), nullable=True
    )
    verified_main_ceremony: Mapped[bool] = mapped_column(Boolean, default=False)

    ceremony: Mapped[Ceremony] = relationship(back_populates="transcript_links")


class VideoLink(Base):
    __tablename__ = "video_links"

    video_link_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ceremony_id: Mapped[int] = mapped_column(ForeignKey("ceremonies.ceremony_id"), index=True)
    ipeds_id: Mapped[int] = mapped_column(Integer, index=True)
    source_tier: Mapped[int] = mapped_column(Integer, default=3)
    platform: Mapped[VideoPlatform] = mapped_column(Enum(VideoPlatform))
    url: Mapped[str] = mapped_column(String(1024))
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    is_full_ceremony: Mapped[Optional[bool]] = mapped_column(Boolean)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    ceremony: Mapped[Ceremony] = relationship(back_populates="video_links")


class Source(Base):
    __tablename__ = "sources"

    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind))
    url: Mapped[str] = mapped_column(String(1024))
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    bytes_len: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(512))


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"

    run_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    triggered_by: Mapped[Optional[str]] = mapped_column(String(256))
    mode: Mapped[Optional[str]] = mapped_column(String(64))
    pilot_size: Mapped[Optional[int]] = mapped_column(Integer)
    random_seed: Mapped[Optional[int]] = mapped_column(Integer)
    summary_json: Mapped[Optional[dict]] = mapped_column(JSON)


class PilotSampleLog(Base):
    __tablename__ = "pilot_sample_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seed: Mapped[int] = mapped_column(Integer)
    stratum_key: Mapped[str] = mapped_column(String(128))
    frame_size: Mapped[int] = mapped_column(Integer)
    target_draw: Mapped[int] = mapped_column(Integer)
    actual_draw: Mapped[int] = mapped_column(Integer)
    written_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DiscardedCandidate(Base):
    """Rows we considered but threw out (e.g. per-college convocations) for audit."""

    __tablename__ = "discarded_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ipeds_id: Mapped[int] = mapped_column(Integer, index=True)
    reason: Mapped[str] = mapped_column(String(128))
    source_url: Mapped[Optional[str]] = mapped_column(String(1024))
    raw_extract: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
