import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.scraping import pipeline
from app.web.main import create_app


@pytest.fixture(autouse=True)
def configure_env(monkeypatch):
    monkeypatch.setenv("UKCASE_DATABASE_URL", "sqlite+pysqlite:////tmp/ukcase_webhook.db")
    monkeypatch.setenv("UKCASE_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("UKCASE_ADMIN_USERNAME", "adminuser")
    monkeypatch.setenv("UKCASE_ADMIN_PASSWORD", "securepass")
    monkeypatch.setenv("UKCASE_CHANGEDTECTION_WEBHOOK_SECRET", "testsecret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def client():
    return TestClient(create_app())


def test_webhook_rejects_invalid_secret(monkeypatch, client):
    called = False

    def _stub(segment_id: int):
        nonlocal called
        called = True
        return pipeline.SegmentRunResult(
            run=type("Run", (), {"id": 1, "status": "SUCCESS"})(),
            total_entries=0,
            new_judgments=0,
            skipped_existing=0,
            failed_items=0,
        )

    monkeypatch.setattr(pipeline, "run_incremental_for_segment", _stub)

    response = client.post("/webhook/changedetection", params={"segment_id": 1, "secret": "wrong"})
    assert response.status_code == 403
    assert called is False


def test_webhook_triggers_incremental(monkeypatch, client):
    fake_run = type(
        "Run",
        (),
        {
            "id": 42,
            "status": "SUCCESS",
        },
    )()
    fake_result = pipeline.SegmentRunResult(
        run=fake_run,
        total_entries=5,
        new_judgments=2,
        skipped_existing=1,
        failed_items=0,
    )

    monkeypatch.setattr(pipeline, "run_incremental_for_segment", lambda segment_id: fake_result)

    response = client.post(
        "/webhook/changedetection",
        params={"segment_id": 7, "secret": "testsecret"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == 42
    assert payload["segment_id"] == 7
    assert payload["status"] == "SUCCESS"
    assert payload["new_judgments"] == 2
    assert payload["skipped_existing"] == 1
