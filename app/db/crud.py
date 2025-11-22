from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Judgment, Run, RunItem, RunType, Segment
from app.scraping.xml_parse import JudgmentMetadata


def create_run(
    session: Session,
    *,
    segment: Segment,
    run_type: RunType,
    trigger_type: str = "SYSTEM",
) -> Run:
    """Create a Run row for a segment and return it (flushed)."""

    now = datetime.now(timezone.utc)
    run = Run(
        segment_id=segment.id,
        trigger_type=trigger_type,
        run_type=run_type,
        started_at=now,
        status="RUNNING",
        total_entries=0,
        new_judgments=0,
        skipped_existing=0,
        failed_items=0,
    )
    session.add(run)
    session.flush()
    return run


def mark_run_success(session: Session, run: Run) -> None:
    run.status = "SUCCESS"
    run.finished_at = datetime.now(timezone.utc)


def mark_run_failure(session: Session, run: Run, exc: BaseException) -> None:
    run.status = "FAILED"
    run.finished_at = datetime.now(timezone.utc)
    run.error_message = str(exc)[:2000]


def get_judgment_by_canonical_uri(session: Session, canonical_uri: str) -> Optional[Judgment]:
    """Return a Judgment by canonical_uri, or None if not found."""

    statement = select(Judgment).where(Judgment.canonical_uri == canonical_uri)
    return session.execute(statement).scalar_one_or_none()


def create_judgment_from_metadata(
    session: Session,
    *,
    canonical_uri: str,
    metadata: JudgmentMetadata,
    xml_path: str,
    first_seen_segment_id: Optional[int] = None,
) -> Judgment:
    """Create and persist a new Judgment row based on parsed metadata."""

    now = datetime.now(timezone.utc)
    judgment = Judgment(
        canonical_uri=canonical_uri,
        neutral_citation=metadata.neutral_citation,
        neutral_citation_number=metadata.neutral_citation_number,
        court_code=metadata.court_code,
        decision_date=metadata.decision_date,
        title=metadata.title,
        parties=metadata.parties,
        judge=metadata.judge,
        xml_path=xml_path,
        xml_downloaded_at=now,
        status="DOWNLOADED",
        first_seen_segment_id=first_seen_segment_id,
        first_seen_at=now,
        rag_status="NOT_PROCESSED",
    )

    session.add(judgment)
    session.flush()
    return judgment


def create_run_item(
    session: Session,
    *,
    run: Run,
    canonical_uri: str,
    xml_url: str,
) -> RunItem:
    item = RunItem(
        run_id=run.id,
        canonical_uri=canonical_uri,
        xml_url=xml_url,
        status="PENDING",
        started_at=datetime.now(timezone.utc),
    )
    session.add(item)
    session.flush()
    return item


def mark_run_item_success(
    session: Session,
    item: RunItem,
    *,
    xml_path: str,
    judgment_id: Optional[int] = None,
) -> None:
    item.status = "SUCCESS"
    item.xml_path = xml_path
    item.judgment_id = judgment_id
    item.finished_at = datetime.now(timezone.utc)


def mark_run_item_failure(
    session: Session,
    item: RunItem,
    *,
    error_message: str,
) -> None:
    item.status = "FAILED"
    item.error_message = error_message[:2000]
    item.finished_at = datetime.now(timezone.utc)
