import os
from datetime import date, datetime
from typing import Callable
from pathlib import Path
import sys
import types

import pytest

pytest.importorskip("sqlalchemy", reason="SQLAlchemy is required for pipeline integration tests")

# Ensure settings resolve even if dependencies are absent in the test environment.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

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


# Minimal environment defaults for Settings before importing app modules.
os.environ.setdefault("UKCASE_DATABASE_URL", "sqlite+pysqlite:////tmp/ukcase_pipeline_tests.db")
os.environ.setdefault("UKCASE_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("UKCASE_ADMIN_USERNAME", "admin")
os.environ.setdefault("UKCASE_ADMIN_PASSWORD", "password")
os.environ.setdefault("UKCASE_XML_STORAGE_ROOT", "/tmp/ukcase_xml_tests")

from app.db.base import Base, SessionLocal, engine
from app.db import crud
from app.db.models import Judgment, RunItem, Segment
from app.scraping.feeds import AtomEntry
from app.scraping.xml_parse import JudgmentMetadata, MetadataParseError
from app.scraping import pipeline


@pytest.fixture(autouse=True)
def reset_db(tmp_path):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    os.makedirs(os.environ["UKCASE_XML_STORAGE_ROOT"], exist_ok=True)
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
def segment(db_session):
    seg = Segment(name="segment", description="", query="test")
    db_session.add(seg)
    db_session.commit()
    return seg


@pytest.fixture()
def fake_metadata():
    return JudgmentMetadata(
        neutral_citation="[2024] EWHC 123",
        neutral_citation_number=123,
        court_code="ewhc/comm",
        decision_date=date(2024, 1, 2),
        title="Example v Example",
        parties=None,
        judge=None,
    )


def make_entry(path: str) -> AtomEntry:
    return AtomEntry(
        canonical_uri=path,
        link=f"https://caselaw.nationalarchives.gov.uk{path}",
        title="Title",
        updated=datetime(2024, 1, 1),
        published=datetime(2024, 1, 1),
    )


def stub_pipeline_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    entries: list[AtomEntry],
    xml_path_factory: Callable[[str], str],
    metadata_factory: Callable[[bytes], JudgmentMetadata],
):
    monkeypatch.setattr(pipeline, "build_atom_url_for_segment", lambda segment: "http://example.com/feed")
    monkeypatch.setattr(pipeline, "fetch_atom_entries", lambda seg: entries)
    monkeypatch.setattr(pipeline, "respect_rate_limit", lambda segment: None)
    monkeypatch.setattr(pipeline, "download_xml_for_canonical_uri", lambda canonical_uri: (f"http://example.com{canonical_uri}/data.xml", b"<xml></xml>"))
    monkeypatch.setattr(pipeline, "store_xml_to_disk", lambda canonical_uri, xml_bytes: xml_path_factory(canonical_uri))
    monkeypatch.setattr(pipeline, "parse_judgment_metadata_from_xml", metadata_factory)


def test_backfill_creates_new_judgments(monkeypatch, db_session, segment, fake_metadata, tmp_path):
    entries = [make_entry("/case/1"), make_entry("/case/2")]

    def xml_path_factory(canonical_uri: str) -> str:
        path = tmp_path / canonical_uri.strip("/") / "data.xml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("data")
        return str(path)

    stub_pipeline_dependencies(
        monkeypatch,
        entries=entries,
        xml_path_factory=xml_path_factory,
        metadata_factory=lambda xml_bytes: fake_metadata,
    )

    result = pipeline.run_backfill_for_segment(segment.id)

    judgments = db_session.query(Judgment).all()
    assert len(judgments) == 2
    assert result.new_judgments == 2
    assert result.skipped_existing == 0
    assert result.failed_items == 0
    assert result.total_entries == 2
    assert result.run.status == "SUCCESS"

    run_items = db_session.query(RunItem).all()
    assert all(item.status == "SUCCESS" and item.xml_path for item in run_items)


def test_backfill_skips_existing(monkeypatch, db_session, segment, fake_metadata, tmp_path):
    existing_path = tmp_path / "case" / "existing" / "data.xml"
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text("existing")
    crud.create_judgment_from_metadata(
        db_session,
        canonical_uri="/case/existing",
        metadata=fake_metadata,
        xml_path=str(existing_path),
        first_seen_segment_id=segment.id,
    )
    db_session.commit()

    entries = [make_entry("/case/existing"), make_entry("/case/new")]

    def xml_path_factory(canonical_uri: str) -> str:
        path = tmp_path / canonical_uri.strip("/") / "data.xml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("data")
        return str(path)

    stub_pipeline_dependencies(
        monkeypatch,
        entries=entries,
        xml_path_factory=xml_path_factory,
        metadata_factory=lambda xml_bytes: fake_metadata,
    )

    result = pipeline.run_backfill_for_segment(segment.id)

    judgments = db_session.query(Judgment).all()
    assert len(judgments) == 2
    assert result.new_judgments == 1
    assert result.skipped_existing == 1
    assert result.total_entries == 2
    assert result.run.status == "SUCCESS"
    run_items = db_session.query(RunItem).all()
    statuses = {item.canonical_uri: item.status for item in run_items}
    assert statuses["/case/existing"] == "SKIPPED_EXISTING"
    assert statuses["/case/new"] == "SUCCESS"


def test_incremental_processes_only_new(monkeypatch, db_session, segment, fake_metadata, tmp_path):
    paths = ["/case/1", "/case/2"]
    for path in paths:
        stub_path = tmp_path / path.strip("/") / "data.xml"
        stub_path.parent.mkdir(parents=True, exist_ok=True)
        stub_path.write_text("data")
        crud.create_judgment_from_metadata(
            db_session,
            canonical_uri=path,
            metadata=fake_metadata,
            xml_path=str(stub_path),
            first_seen_segment_id=segment.id,
        )
    db_session.commit()

    entries = [make_entry(path) for path in paths]

    stub_pipeline_dependencies(
        monkeypatch,
        entries=entries,
        xml_path_factory=lambda canonical_uri: "",  # should not be called
        metadata_factory=lambda xml_bytes: fake_metadata,
    )

    result = pipeline.run_incremental_for_segment(segment.id)

    run_items = db_session.query(RunItem).all()
    assert len(run_items) == len(paths)
    assert all(item.status == "SKIPPED_EXISTING" for item in run_items)
    assert result.new_judgments == 0
    assert result.skipped_existing == len(paths)
    assert result.total_entries == len(paths)
    assert result.run.status == "SUCCESS"


def test_per_entry_failure_is_recorded(monkeypatch, db_session, segment, fake_metadata, tmp_path):
    entries = [make_entry("/case/good"), make_entry("/case/bad")]

    def metadata_factory(xml_bytes: bytes) -> JudgmentMetadata:
        if b"bad" in xml_bytes:
            raise MetadataParseError("broken metadata")
        return fake_metadata

    def download_stub(canonical_uri: str):
        content = b"bad" if canonical_uri.endswith("bad") else b"good"
        return f"http://example.com{canonical_uri}/data.xml", content

    def xml_path_factory(canonical_uri: str) -> str:
        path = tmp_path / canonical_uri.strip("/") / "data.xml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("data")
        return str(path)

    monkeypatch.setattr(pipeline, "build_atom_url_for_segment", lambda segment: "http://example.com/feed")
    monkeypatch.setattr(pipeline, "fetch_atom_entries", lambda url: entries)
    monkeypatch.setattr(pipeline, "respect_rate_limit", lambda segment: None)
    monkeypatch.setattr(pipeline, "download_xml_for_canonical_uri", download_stub)
    monkeypatch.setattr(pipeline, "store_xml_to_disk", lambda canonical_uri, xml_bytes: xml_path_factory(canonical_uri))
    monkeypatch.setattr(pipeline, "parse_judgment_metadata_from_xml", metadata_factory)

    result = pipeline.run_backfill_for_segment(segment.id)

    run_items = {item.canonical_uri: item for item in db_session.query(RunItem).all()}
    assert run_items["/case/bad"].status == "FAILED"
    assert run_items["/case/good"].status == "SUCCESS"
    assert result.failed_items == 1
    assert result.new_judgments == 1
    assert result.total_entries == 2
    assert result.run.status == "PARTIAL_SUCCESS"


def test_all_entries_fail_sets_run_status_failed(monkeypatch, db_session, segment, tmp_path):
    entries = [make_entry("/case/fail1"), make_entry("/case/fail2")]

    def metadata_factory(xml_bytes: bytes):
        raise MetadataParseError("bad metadata")

    def xml_path_factory(canonical_uri: str) -> str:
        path = tmp_path / canonical_uri.strip("/") / "data.xml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("data")
        return str(path)

    stub_pipeline_dependencies(
        monkeypatch,
        entries=entries,
        xml_path_factory=xml_path_factory,
        metadata_factory=metadata_factory,
    )

    result = pipeline.run_backfill_for_segment(segment.id)

    judgments = db_session.query(Judgment).all()
    assert len(judgments) == 0
    assert result.new_judgments == 0
    assert result.failed_items == 2
    assert result.skipped_existing == 0
    assert result.total_entries == 2
    assert result.run.status == "FAILED"

    run_items = db_session.query(RunItem).order_by(RunItem.canonical_uri).all()
    assert [item.status for item in run_items] == ["FAILED", "FAILED"]
    assert all(item.error_message for item in run_items)


def test_run_failure_records_status(monkeypatch, segment):
    monkeypatch.setattr(pipeline, "build_atom_url_for_segment", lambda segment: "http://example.com/feed")
    monkeypatch.setattr(pipeline, "fetch_atom_entries", lambda url: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        pipeline.run_backfill_for_segment(segment.id)

    with SessionLocal() as session:
        run = session.query(pipeline.Run).order_by(pipeline.Run.id.desc()).first()
        assert run.status == "FAILED"
        assert run.finished_at is not None
        assert run.error_message
        assert session.query(RunItem).count() == 0
