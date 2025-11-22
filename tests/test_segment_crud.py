from datetime import date
import os
import sys
import types

import pytest

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

os.environ.setdefault("UKCASE_DATABASE_URL", "sqlite+pysqlite:////tmp/ukcase_segment_crud.db")
os.environ.setdefault("UKCASE_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("UKCASE_ADMIN_USERNAME", "admin")
os.environ.setdefault("UKCASE_ADMIN_PASSWORD", "password")

from app.db.base import Base, SessionLocal, engine
from app.db import crud
from app.db.models import Segment


@pytest.fixture(autouse=True)
def reset_db(tmp_path):
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


def test_create_segment_defaults(db_session):
    segment = crud.create_segment(db_session, name="segment-one")
    db_session.commit()

    fetched = crud.get_segment_by_id(db_session, segment.id)
    assert fetched is not None
    assert fetched.backfill_mode == "NEW_ONLY"
    assert float(fetched.rate_limit_seconds) == 1.5
    assert fetched.is_active is True


def test_get_segment_by_name(db_session):
    segment = crud.create_segment(db_session, name="alpha", query="q")
    db_session.commit()

    assert crud.get_segment_by_name(db_session, "alpha") == segment
    assert crud.get_segment_by_id(db_session, segment.id) == segment
    assert crud.get_segment_by_name(db_session, "missing") is None


def test_update_segment_fields(db_session):
    segment = crud.create_segment(
        db_session,
        name="beta",
        query="initial",
        courts=["ewhc/ch"],
        backfill_mode="NEW_ONLY",
        rate_limit_seconds=1.5,
    )
    db_session.commit()

    crud.update_segment(
        db_session,
        segment,
        query="updated",
        courts=["ewhc/comm", "ewhc/kb"],
        backfill_mode="FULL_HISTORY",
        decision_date_from=date(2020, 1, 1),
        decision_date_to=date(2020, 12, 31),
    )
    db_session.commit()

    fetched = crud.get_segment_by_id(db_session, segment.id)
    assert fetched is not None
    assert fetched.query == "updated"
    assert fetched.courts == ["ewhc/comm", "ewhc/kb"]
    assert fetched.backfill_mode == "FULL_HISTORY"
    assert fetched.decision_date_from == date(2020, 1, 1)
    assert fetched.decision_date_to == date(2020, 12, 31)


def test_update_segment_unknown_field(db_session):
    segment = crud.create_segment(db_session, name="gamma")
    db_session.commit()

    with pytest.raises(AttributeError):
        crud.update_segment(db_session, segment, nonexistent=True)


def test_delete_segment(db_session):
    segment = crud.create_segment(db_session, name="delta")
    db_session.commit()

    crud.delete_segment(db_session, segment)
    db_session.commit()

    assert crud.get_segment_by_id(db_session, segment.id) is None
    assert crud.get_segment_by_name(db_session, "delta") is None
