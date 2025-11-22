from __future__ import annotations

from types import SimpleNamespace

from app.workers import jobs


class DummyResult:
    """Simple stand-in for pipeline.SegmentRunResult."""

    def __init__(self, run_id: int, run_type: str, status: str = "FINISHED"):
        self.run = SimpleNamespace(id=run_id, run_type=run_type, status=status)
        self.total_entries = 10
        self.new_judgments = 3
        self.skipped_existing = 6
        self.failed_items = 1


def test_summary_normalises_enum_like_values(monkeypatch):
    class FakeEnum:
        def __init__(self, value: str):
            self.value = value

    class EnumLikeResult:
        def __init__(self):
            self.run = SimpleNamespace(
                id=123,
                run_type=FakeEnum("BACKFILL"),
                status=FakeEnum("SUCCESS"),
            )
            self.total_entries = 1
            self.new_judgments = 1
            self.skipped_existing = 0
            self.failed_items = 0

    monkeypatch.setattr(
        jobs.pipeline, "run_backfill_for_segment", lambda segment_id, max_entries=None: EnumLikeResult()
    )

    summary = jobs.backfill_segment(segment_id=10)

    assert summary["run_id"] == 123
    assert summary["segment_id"] == 10
    assert summary["run_type"] == "BACKFILL"
    assert summary["status"] == "SUCCESS"


def test_backfill_segment_delegates_to_pipeline(monkeypatch):
    calls: dict[str, object] = {}

    def fake_run_backfill_for_segment(segment_id: int, max_entries=None):
        calls["args"] = (segment_id, max_entries)
        return DummyResult(run_id=42, run_type="BACKFILL")

    monkeypatch.setattr(jobs.pipeline, "run_backfill_for_segment", fake_run_backfill_for_segment)

    summary = jobs.backfill_segment(segment_id=5, max_entries=100)

    assert calls["args"] == (5, 100)
    assert summary == {
        "run_id": 42,
        "segment_id": 5,
        "run_type": "BACKFILL",
        "status": "FINISHED",
        "total_entries": 10,
        "new_judgments": 3,
        "skipped_existing": 6,
        "failed_items": 1,
    }


def test_incremental_segment_run_delegates_to_pipeline(monkeypatch):
    calls: dict[str, object] = {}

    def fake_run_incremental_for_segment(segment_id: int):
        calls["args"] = (segment_id,)
        return DummyResult(run_id=99, run_type="INCREMENTAL", status="SUCCESS")

    monkeypatch.setattr(jobs.pipeline, "run_incremental_for_segment", fake_run_incremental_for_segment)

    summary = jobs.incremental_segment_run(segment_id=7)

    assert calls["args"] == (7,)
    assert summary["run_id"] == 99
    assert summary["segment_id"] == 7
    assert summary["run_type"] == "INCREMENTAL"
    assert summary["status"] == "SUCCESS"


def test_enqueue_backfill_segment_uses_queue(monkeypatch):
    class DummyQueue:
        def __init__(self):
            self.enqueued = []

        def enqueue(self, func, *args, **kwargs):
            self.enqueued.append((func, args, kwargs))
            return "DUMMY_JOB"

    dummy_queue = DummyQueue()
    monkeypatch.setattr(jobs, "get_default_queue", lambda queue_name="ukcase": dummy_queue)

    job = jobs.enqueue_backfill_segment(segment_id=11, max_entries=50, queue_name="custom")

    assert job == "DUMMY_JOB"
    assert len(dummy_queue.enqueued) == 1
    func, args, kwargs = dummy_queue.enqueued[0]
    assert func is jobs.backfill_segment
    assert args == (11,)
    assert kwargs == {"max_entries": 50}


def test_enqueue_incremental_segment_uses_queue(monkeypatch):
    class DummyQueue:
        def __init__(self):
            self.enqueued = []

        def enqueue(self, func, *args, **kwargs):
            self.enqueued.append((func, args, kwargs))
            return "DUMMY_JOB"

    dummy_queue = DummyQueue()
    monkeypatch.setattr(jobs, "get_default_queue", lambda queue_name="ukcase": dummy_queue)

    job = jobs.enqueue_incremental_segment(segment_id=13, queue_name="custom")

    assert job == "DUMMY_JOB"
    assert len(dummy_queue.enqueued) == 1
    func, args, kwargs = dummy_queue.enqueued[0]
    assert func is jobs.incremental_segment_run
    assert args == (13,)
    assert kwargs == {}
