from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from redis import Redis
from rq import Queue

from app.config import get_settings
from app.scraping import pipeline


@dataclass
class SegmentRunSummary:
    run_id: int
    segment_id: int
    run_type: str
    status: str
    total_entries: int
    new_judgments: int
    skipped_existing: int
    failed_items: int


def get_redis_connection() -> Redis:
    """Create a Redis connection using the configured Redis URL."""

    settings = get_settings()
    return Redis.from_url(settings.redis_url)


def get_default_queue(queue_name: str = "ukcase") -> Queue:
    """Return the default RQ queue for this application."""

    connection = get_redis_connection()
    return Queue(name=queue_name, connection=connection)


def _enum_like_to_str(value: object, default: str = "UNKNOWN") -> str:
    """Normalise Enum-like values to a plain string.

    Uses ``value`` when it exposes a ``.value`` attribute (e.g. Enum members),
    falling back to ``str(value)``. Returns ``default`` when ``value`` is ``None``
    or cannot be coerced.
    """

    if value is None:
        return default

    raw_value = getattr(value, "value", value)
    try:
        return str(raw_value)
    except Exception:  # pragma: no cover - extremely defensive
        return default


def _summary_from_result(segment_id: int, result: pipeline.SegmentRunResult) -> SegmentRunSummary:
    """Build a serialisable summary from a SegmentRunResult."""

    run = result.run
    return SegmentRunSummary(
        run_id=run.id,
        segment_id=segment_id,
        run_type=_enum_like_to_str(getattr(run, "run_type", None)),
        status=_enum_like_to_str(getattr(run, "status", None)),
        total_entries=result.total_entries,
        new_judgments=result.new_judgments,
        skipped_existing=result.skipped_existing,
        failed_items=result.failed_items,
    )


def backfill_segment(segment_id: int, max_entries: Optional[int] = None) -> dict:
    """RQ job wrapper: perform a backfill run for a specific segment."""

    result = pipeline.run_backfill_for_segment(segment_id, max_entries=max_entries)
    summary = _summary_from_result(segment_id, result)
    return asdict(summary)


def incremental_segment_run(segment_id: int) -> dict:
    """RQ job wrapper: perform an incremental run for a specific segment."""

    result = pipeline.run_incremental_for_segment(segment_id)
    summary = _summary_from_result(segment_id, result)
    return asdict(summary)


def enqueue_backfill_segment(
    segment_id: int,
    max_entries: Optional[int] = None,
    queue_name: str = "ukcase",
):
    """Enqueue a backfill_segment job into the given queue."""

    queue = get_default_queue(queue_name=queue_name)
    return queue.enqueue(backfill_segment, segment_id, max_entries=max_entries)


def enqueue_incremental_segment(
    segment_id: int,
    queue_name: str = "ukcase",
):
    """Enqueue an incremental_segment_run job into the given queue."""

    queue = get_default_queue(queue_name=queue_name)
    return queue.enqueue(incremental_segment_run, segment_id)
