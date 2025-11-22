from __future__ import annotations

from datetime import date, datetime
import enum
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RunType(str, enum.Enum):
    BACKFILL = "BACKFILL"
    INCREMENTAL = "INCREMENTAL"


class Segment(Base):
    __tablename__ = "segments"
    __table_args__ = (
        Index("idx_segments_active", "active"),
        Index("idx_segments_changedetection_token", "changedetection_token"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    query: Mapped[Optional[str]] = mapped_column(Text)
    courts: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text))
    party: Mapped[Optional[str]] = mapped_column(Text)
    judge_filter: Mapped[Optional[str]] = mapped_column(Text)
    neutral_citation_filter: Mapped[Optional[str]] = mapped_column(Text)
    date_from: Mapped[Optional[date]] = mapped_column(Date)
    date_to: Mapped[Optional[date]] = mapped_column(Date)

    raw_atom_url: Mapped[Optional[str]] = mapped_column(Text)

    backfill_mode: Mapped[str] = mapped_column(Text, server_default=text("'NEW_ONLY'"), nullable=False)
    backfill_since_date: Mapped[Optional[date]] = mapped_column(Date)

    rate_limit_seconds: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), server_default=text("1.5"))

    changedetection_token: Mapped[Optional[str]] = mapped_column(Text, unique=True)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    runs: Mapped[List[Run]] = relationship("Run", back_populates="segment", cascade="all, delete-orphan")
    first_seen_judgments: Mapped[List[Judgment]] = relationship("Judgment", back_populates="first_seen_segment")


class Judgment(Base):
    __tablename__ = "judgments"
    __table_args__ = (
        Index("idx_judgments_decision_date", "decision_date"),
        Index("idx_judgments_court_code_decision_date", "court_code", "decision_date"),
        Index("idx_judgments_rag_status", "rag_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    canonical_uri: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    neutral_citation: Mapped[str] = mapped_column(Text, nullable=False)
    neutral_citation_number: Mapped[Optional[int]] = mapped_column(Integer)
    court_code: Mapped[str] = mapped_column(Text, nullable=False)
    decision_date: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    parties: Mapped[Optional[str]] = mapped_column(Text)
    judge: Mapped[Optional[str]] = mapped_column(Text)

    xml_path: Mapped[str] = mapped_column(Text, nullable=False)
    xml_downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'DOWNLOADED'"))

    rag_status: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'NOT_PROCESSED'"))
    rag_last_processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rag_version: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("1"))
    rag_external_id: Mapped[Optional[str]] = mapped_column(Text)

    first_seen_segment_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("segments.id"))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    first_seen_segment: Mapped[Optional[Segment]] = relationship("Segment", back_populates="first_seen_judgments")
    run_items: Mapped[List[RunItem]] = relationship("RunItem", back_populates="judgment")


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (Index("idx_runs_segment_started_at", "segment_id", "started_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    segment_id: Mapped[int] = mapped_column(Integer, ForeignKey("segments.id"), nullable=False)

    trigger_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'UNKNOWN'"))
    run_type: Mapped[str] = mapped_column(Text, nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'RUNNING'"))

    total_entries: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    new_judgments: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    skipped_existing: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    failed_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    error_message: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    segment: Mapped[Segment] = relationship("Segment", back_populates="runs")
    run_items: Mapped[List[RunItem]] = relationship("RunItem", back_populates="run", cascade="all, delete-orphan")


class RunItem(Base):
    __tablename__ = "run_items"
    __table_args__ = (
        Index("idx_run_items_run_id", "run_id"),
        Index("idx_run_items_canonical_uri", "canonical_uri"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    judgment_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("judgments.id"))
    canonical_uri: Mapped[str] = mapped_column(Text, nullable=False)

    xml_url: Mapped[Optional[str]] = mapped_column(Text)
    xml_path: Mapped[Optional[str]] = mapped_column(Text)

    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'PENDING'"))
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped[Run] = relationship("Run", back_populates="run_items")
    judgment: Mapped[Optional[Judgment]] = relationship("Judgment", back_populates="run_items")
