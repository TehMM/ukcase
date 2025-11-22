from __future__ import annotations

from app.workers import worker as worker_module


def test_worker_main_uses_connection_and_worker(monkeypatch):
    calls: dict[str, object] = {}

    class DummyWorker:
        def __init__(self, queues):
            calls["queues"] = queues

        def work(self):
            calls["worked"] = True

    class DummyConnection:
        def __init__(self, conn):
            calls["connection"] = conn

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(worker_module, "Worker", DummyWorker)
    monkeypatch.setattr(worker_module, "Connection", DummyConnection)
    monkeypatch.setattr(worker_module, "get_redis_connection", lambda: "DUMMY_CONN")

    worker_module.main(queue_name="ukcase-test")

    assert calls["connection"] == "DUMMY_CONN"
    assert calls["queues"] == ["ukcase-test"]
    assert calls["worked"] is True
