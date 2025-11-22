from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.base import Base, SessionLocal, engine
from app.db import crud
from app.db.models import Run, RunItem, RunType, Segment
from app.scraping import pipeline
from app.web.main import create_app


@pytest.fixture(autouse=True)
def configure_env(monkeypatch):
    monkeypatch.setenv("UKCASE_DATABASE_URL", "sqlite+pysqlite:////tmp/ukcase_web_admin.db")
    monkeypatch.setenv("UKCASE_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("UKCASE_ADMIN_USERNAME", "adminuser")
    monkeypatch.setenv("UKCASE_ADMIN_PASSWORD", "securepass")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client():
    return TestClient(create_app())


@pytest.fixture()
def segment(db_session: SessionLocal):
    seg = crud.create_segment(db_session, name="segment-one", query="alpha")
    db_session.commit()
    return seg


def _build_run(segment: Segment, run_type: RunType = RunType.BACKFILL) -> Run:
    now = datetime.now(timezone.utc)
    return Run(
        id=123,
        segment_id=segment.id,
        run_type=run_type.value,
        status="SUCCESS",
        started_at=now,
        finished_at=now,
        total_entries=2,
        new_judgments=1,
        skipped_existing=0,
        failed_items=0,
    )


def test_segments_requires_auth(client):
    response = client.get("/admin/segments")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Basic"


def test_segments_lists_entries(client, segment):
    response = client.get("/admin/segments", auth=("adminuser", "securepass"))
    assert response.status_code == 200
    assert segment.name in response.text


def test_run_backfill_renders_result(monkeypatch, client, segment):
    fake_run = _build_run(segment, RunType.BACKFILL)
    fake_result = pipeline.SegmentRunResult(
        run=fake_run,
        total_entries=2,
        new_judgments=1,
        skipped_existing=0,
        failed_items=0,
    )

    monkeypatch.setattr(pipeline, "run_backfill_for_segment", lambda segment_id: fake_result)

    response = client.post(
        f"/admin/segments/{segment.id}/run/backfill",
        auth=("adminuser", "securepass"),
    )
    assert response.status_code == 200
    assert "SUCCESS" in response.text
    assert "new=1" in response.text


def test_run_incremental_renders_result(monkeypatch, client, segment):
    fake_run = _build_run(segment, RunType.INCREMENTAL)
    fake_result = pipeline.SegmentRunResult(
        run=fake_run,
        total_entries=3,
        new_judgments=2,
        skipped_existing=1,
        failed_items=0,
    )

    monkeypatch.setattr(pipeline, "run_incremental_for_segment", lambda segment_id: fake_result)

    response = client.post(
        f"/admin/segments/{segment.id}/run/incremental",
        auth=("adminuser", "securepass"),
    )
    assert response.status_code == 200
    assert "SUCCESS" in response.text
    assert "new=2" in response.text


def test_runs_and_run_detail_views(client, db_session, segment):
    now = datetime.now(timezone.utc)
    run = Run(
        segment_id=segment.id,
        run_type=RunType.BACKFILL.value,
        status="SUCCESS",
        started_at=now,
        finished_at=now,
        total_entries=1,
        new_judgments=1,
        skipped_existing=0,
        failed_items=0,
    )
    item = RunItem(
        run=run,
        canonical_uri="/case/1",
        status="SUCCESS",
        error_message=None,
    )
    db_session.add(run)
    item.run_id = run.id
    db_session.add(item)
    db_session.commit()

    list_response = client.get("/admin/runs", auth=("adminuser", "securepass"))
    assert list_response.status_code == 200
    assert str(run.id) in list_response.text

    detail_response = client.get(f"/admin/runs/{run.id}", auth=("adminuser", "securepass"))
    assert detail_response.status_code == 200
    assert run.status in detail_response.text
    assert item.canonical_uri in detail_response.text


def test_run_detail_missing_returns_404(client, segment):
    response = client.get("/admin/runs/9999", auth=("adminuser", "securepass"))
    assert response.status_code == 404
