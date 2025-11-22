from __future__ import annotations

from datetime import date, datetime, timezone
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
    trigger_type: str = "UNKNOWN",
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
    """Set the final status for a run based on counters."""

    now = datetime.now(timezone.utc)
    if run.failed_items > 0 and run.new_judgments > 0:
        run.status = "PARTIAL_SUCCESS"
    elif run.failed_items > 0 and run.new_judgments == 0:
        run.status = "FAILED"
    else:
        run.status = "SUCCESS"
    run.finished_at = now


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


def mark_run_item_skipped_existing(
    session: Session,
    item: RunItem,
    *,
    judgment_id: int,
) -> None:
    item.status = "SKIPPED_EXISTING"
    item.judgment_id = judgment_id
    item.finished_at = datetime.now(timezone.utc)


def list_segments(session: Session) -> list[Segment]:
    """Return all segments ordered by id."""

    stmt = select(Segment).order_by(Segment.id)
    return list(session.execute(stmt).scalars())


def get_segment_by_id(session: Session, segment_id: int) -> Optional[Segment]:
    """Return a Segment by id or None if it does not exist."""

    return session.get(Segment, segment_id)


def get_segment_by_name(session: Session, name: str) -> Optional[Segment]:
    """Return a Segment by name or None if not found."""

    stmt = select(Segment).where(Segment.name == name)
    return session.execute(stmt).scalar_one_or_none()


def create_segment(
    session: Session,
    *,
    name: str,
    description: Optional[str] = None,
    query: Optional[str] = None,
    courts: Optional[list[str]] = None,
    decision_date_from: Optional[date] = None,
    decision_date_to: Optional[date] = None,
    backfill_mode: str = "NEW_ONLY",
    rate_limit_seconds: float = 1.5,
    is_active: bool = True,
) -> Segment:
    """Create and persist a Segment with the provided fields."""

    segment = Segment(
        name=name,
        description=description,
        query=query,
        courts=courts,
        decision_date_from=decision_date_from,
        decision_date_to=decision_date_to,
        backfill_mode=backfill_mode,
        rate_limit_seconds=rate_limit_seconds,
        is_active=is_active,
    )
    session.add(segment)
    session.flush()
    return segment


def update_segment(session: Session, segment: Segment, **fields: object) -> Segment:
    """Update attributes on a Segment instance and flush the session."""

    for key, value in fields.items():
        if not hasattr(segment, key):
            raise AttributeError(f"Segment has no attribute {key!r}")
        setattr(segment, key, value)
    session.flush()
    return segment


def delete_segment(session: Session, segment: Segment) -> None:
    """Delete a Segment instance and flush the session."""

    session.delete(segment)
    session.flush()


def list_recent_runs(session: Session, limit: int = 50) -> list[Run]:
    """Return recent runs ordered by start time descending."""

    stmt = select(Run).order_by(Run.started_at.desc()).limit(limit)
    return list(session.execute(stmt).scalars())


def get_run_with_items(session: Session, run_id: int) -> tuple[Run, list[RunItem]]:
    """Return a run and its associated items."""

    run = session.get(Run, run_id)
    if run is None:
        raise ValueError(f"Run {run_id} not found")

    items = (
        session.execute(select(RunItem).where(RunItem.run_id == run.id).order_by(RunItem.id))
        .scalars()
        .all()
    )
    return run, items
