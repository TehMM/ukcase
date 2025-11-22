import os
import sys
import types
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

# Provide stubs if pydantic_settings is unavailable in the test environment.
if "pydantic_settings" not in sys.modules:  # pragma: no cover
    pydantic_settings = types.ModuleType("pydantic_settings")

    class BaseSettings:  # pragma: no cover
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    class SettingsConfigDict(dict):  # pragma: no cover
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    pydantic_settings.BaseSettings = BaseSettings
    pydantic_settings.SettingsConfigDict = SettingsConfigDict
    sys.modules["pydantic_settings"] = pydantic_settings

os.environ.setdefault("UKCASE_DATABASE_URL", "sqlite+pysqlite:////tmp/ukcase_cli.db")
os.environ.setdefault("UKCASE_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("UKCASE_ADMIN_USERNAME", "admin")
os.environ.setdefault("UKCASE_ADMIN_PASSWORD", "password")

from app.cli import app
from app.db.base import Base, SessionLocal, engine
from app.db import crud
from app.db.models import Segment

runner = CliRunner()


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _create_segment(name: str = "seg1") -> Segment:
    with SessionLocal() as session:
        segment = crud.create_segment(session, name=name)
        session.commit()
        return segment


def test_segment_list_empty():
    result = runner.invoke(app, ["segment", "list"])

    assert result.exit_code == 0
    assert "No segments." in result.stdout


def test_segment_create_and_duplicate():
    result = runner.invoke(app, ["segment", "create", "alpha", "--query", "q"])
    assert result.exit_code == 0
    assert "Created segment" in result.stdout

    # Duplicate name fails
    duplicate = runner.invoke(app, ["segment", "create", "alpha"])
    assert duplicate.exit_code == 1
    assert "already exists" in duplicate.stdout

    with SessionLocal() as session:
        segment = crud.get_segment_by_name(session, "alpha")
        assert segment is not None
        assert segment.query == "q"


def test_segment_create_rejects_bad_date_and_backfill():
    bad_date = runner.invoke(app, ["segment", "create", "delta", "--decision-date-from", "2020-99-99"])

    assert bad_date.exit_code != 0
    assert "Invalid date format" in bad_date.stdout

    invalid_backfill = runner.invoke(
        app,
        [
            "segment",
            "create",
            "epsilon",
            "--backfill-mode",
            "FULL_HISTORIC",
        ],
    )

    assert invalid_backfill.exit_code != 0
    assert "Allowed values" in invalid_backfill.stdout


def test_run_backfill_command(monkeypatch):
    _create_segment("beta")

    fake_result = SimpleNamespace(
        run=SimpleNamespace(id=1, status="SUCCESS"),
        total_entries=3,
        new_judgments=2,
        skipped_existing=1,
        failed_items=0,
    )

    monkeypatch.setattr(
        "app.cli.pipeline.run_backfill_for_segment",
        lambda segment_id, max_entries=None: fake_result,
    )

    result = runner.invoke(app, ["run", "backfill", "1"])

    assert result.exit_code == 0
    assert "Run 1 BACKFILL for segment 1" in result.stdout
    assert "total=3" in result.stdout
    assert "new=2" in result.stdout
    assert "skipped=1" in result.stdout
    assert "failed=0" in result.stdout


def test_run_incremental_command(monkeypatch):
    _create_segment("gamma")

    fake_result = SimpleNamespace(
        run=SimpleNamespace(id=2, status="PARTIAL_SUCCESS"),
        total_entries=4,
        new_judgments=3,
        skipped_existing=0,
        failed_items=1,
    )

    monkeypatch.setattr(
        "app.cli.pipeline.run_incremental_for_segment",
        lambda segment_id: fake_result,
    )

    result = runner.invoke(app, ["run", "incremental", "1"])

    assert result.exit_code == 0
    assert "Run 2 INCREMENTAL for segment 1" in result.stdout
    assert "total=4" in result.stdout
    assert "new=3" in result.stdout
    assert "skipped=0" in result.stdout
    assert "failed=1" in result.stdout
