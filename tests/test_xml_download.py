from __future__ import annotations

import os
import pathlib
import sys
import types
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # Ensure the repository root is importable
    sys.path.insert(0, str(ROOT))

# Stub minimal pydantic_settings interface when the dependency is unavailable.
if "pydantic_settings" not in sys.modules:  # pragma: no cover
    pydantic_settings = types.ModuleType("pydantic_settings")

    class BaseSettings:  # pragma: no cover - simple initializer for tests
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    class SettingsConfigDict(dict):  # pragma: no cover
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    pydantic_settings.BaseSettings = BaseSettings
    pydantic_settings.SettingsConfigDict = SettingsConfigDict
    sys.modules["pydantic_settings"] = pydantic_settings

try:  # pragma: no cover - use installed dependency when available
    import httpx  # type: ignore
except ImportError:  # pragma: no cover
    httpx = types.ModuleType("httpx")

    class Response:
        def __init__(self, status_code: int, text: str, content: bytes | None = None, request=None):
            self.status_code = status_code
            self.text = text
            self.content = content if content is not None else text.encode()
            self.request = request

        def raise_for_status(self):
            if self.status_code >= 400:
                raise HTTPStatusError(f"status {self.status_code}", request=self.request, response=self)

    class HTTPStatusError(Exception):
        def __init__(self, message: str, request=None, response=None):
            super().__init__(message)
            self.request = request
            self.response = response

    class RequestError(Exception):
        def __init__(self, message: str, request=None):  # pragma: no cover - minimal stub
            super().__init__(message)
            self.request = request

    class Codes(SimpleNamespace):
        OK = 200
        TOO_MANY_REQUESTS = 429
        NOT_FOUND = 404
        SERVICE_UNAVAILABLE = 503

    httpx.Response = Response
    httpx.HTTPStatusError = HTTPStatusError
    httpx.RequestError = RequestError
    httpx.codes = Codes()

    def _missing_get(*args, **kwargs):  # pragma: no cover - replaced in tests
        raise RuntimeError("httpx.get stub called without monkeypatch")

    httpx.get = _missing_get
    sys.modules["httpx"] = httpx

# Stub minimal SQLAlchemy interface when unavailable.
if "sqlalchemy" not in sys.modules:  # pragma: no cover
    sqlalchemy = types.ModuleType("sqlalchemy")
    sqlalchemy.orm = types.ModuleType("sqlalchemy.orm")

    class Session:  # pragma: no cover - placeholder
        pass

    sqlalchemy.orm.Session = Session
    sys.modules["sqlalchemy"] = sqlalchemy
    sys.modules["sqlalchemy.orm"] = sqlalchemy.orm

import httpx  # type: ignore  # noqa: E402

if not hasattr(httpx, "RequestError"):
    class _RequestError(Exception):  # pragma: no cover - compatibility shim
        def __init__(self, message: str, request=None):
            super().__init__(message)
            self.request = request

    httpx.RequestError = _RequestError  # type: ignore[attr-defined]

from app.scraping import xml_download  # noqa: E402


@pytest.fixture(autouse=True)
def _mock_settings(monkeypatch, tmp_path):
    fake_settings = SimpleNamespace(
        request_timeout_seconds=5,
        max_http_retries=2,
        http_user_agent="ukcase-tests/0.1",
        xml_storage_root=tmp_path,
    )
    monkeypatch.setattr(xml_download, "get_settings", lambda: fake_settings)


def test_download_xml_success(monkeypatch):
    calls = []
    sleep_calls: list[float] = []

    def fake_get(url: str, timeout: int, headers: dict):
        calls.append((url, headers))
        return httpx.Response(status_code=200, text="<xml />", content=b"<xml />")

    monkeypatch.setattr(xml_download.httpx, "get", fake_get)
    monkeypatch.setattr(xml_download.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    xml_url, content = xml_download.download_xml_for_canonical_uri("/ewhc/comm/2025/3036")

    assert xml_url == "https://caselaw.nationalarchives.gov.uk/ewhc/comm/2025/3036/data.xml"
    assert content == b"<xml />"
    assert len(calls) == 1
    for _, headers in calls:
        assert headers["User-Agent"] == "ukcase-tests/0.1"
    assert sleep_calls == []


def test_download_xml_retries_then_succeeds(monkeypatch):
    calls = []
    sleep_calls: list[float] = []

    def fake_get(url: str, timeout: int, headers: dict):
        calls.append((url, headers))
        if len(calls) == 1:
            return httpx.Response(status_code=503, text="server error")
        return httpx.Response(status_code=200, text="<xml />", content=b"<xml />")

    monkeypatch.setattr(xml_download.httpx, "get", fake_get)
    monkeypatch.setattr(xml_download.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    xml_url, content = xml_download.download_xml_for_canonical_uri("/ewhc/kb/2024/100")

    assert xml_url == "https://caselaw.nationalarchives.gov.uk/ewhc/kb/2024/100/data.xml"
    assert content == b"<xml />"
    assert len(calls) == 2
    assert len(sleep_calls) == 1
    for _, headers in calls:
        assert headers["User-Agent"] == "ukcase-tests/0.1"


def test_download_xml_retries_on_too_many_requests(monkeypatch):
    calls = []
    sleep_calls: list[float] = []

    monkeypatch.setattr(
        xml_download,
        "get_settings",
        lambda: SimpleNamespace(
            request_timeout_seconds=5,
            max_http_retries=3,
            http_user_agent="ukcase-tests/0.1",
            xml_storage_root=pathlib.Path.cwd(),
        ),
    )

    def fake_get(url: str, timeout: int, headers: dict):
        calls.append((url, headers))
        if len(calls) <= 2:
            return httpx.Response(status_code=429, text="slow down")
        return httpx.Response(status_code=200, text="<xml />", content=b"<xml />")

    monkeypatch.setattr(xml_download.httpx, "get", fake_get)
    monkeypatch.setattr(xml_download.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    xml_url, content = xml_download.download_xml_for_canonical_uri("/ewhc/adm/2023/50")

    assert xml_url.endswith("/ewhc/adm/2023/50/data.xml")
    assert content == b"<xml />"
    assert len(calls) == 3
    assert sleep_calls == [0.5, 1.0]
    for _, headers in calls:
        assert headers["User-Agent"] == "ukcase-tests/0.1"


def test_download_xml_raises_on_not_found(monkeypatch):
    sleep_calls: list[float] = []

    def fake_get(url: str, timeout: int, headers: dict):
        return httpx.Response(status_code=404, text="not found")

    monkeypatch.setattr(xml_download.httpx, "get", fake_get)
    monkeypatch.setattr(xml_download.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    with pytest.raises(httpx.HTTPStatusError):
        xml_download.download_xml_for_canonical_uri("/ewhc/ch/2020/1")

    assert sleep_calls == []


def test_download_xml_raises_after_request_errors(monkeypatch):
    sleep_calls: list[float] = []

    def fake_get(url: str, timeout: int, headers: dict):
        raise httpx.RequestError("network down")

    monkeypatch.setattr(
        xml_download,
        "get_settings",
        lambda: SimpleNamespace(
            request_timeout_seconds=5,
            max_http_retries=3,
            http_user_agent="ukcase-tests/0.1",
            xml_storage_root=pathlib.Path.cwd(),
        ),
    )
    monkeypatch.setattr(xml_download.httpx, "get", fake_get)
    monkeypatch.setattr(xml_download.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    with pytest.raises(httpx.RequestError):
        xml_download.download_xml_for_canonical_uri("/ewhc/comm/2021/999")

    assert sleep_calls == [0.5, 1.0]


def test_store_xml_to_disk_writes_structure(tmp_path, monkeypatch):
    monkeypatch.setattr(xml_download, "get_settings", lambda: SimpleNamespace(xml_storage_root=tmp_path))

    path = xml_download.store_xml_to_disk("/ewhc/comm/2025/3036?foo=bar#frag", b"<data />")

    expected_dir = tmp_path / "ewhc" / "comm" / "2025" / "3036"
    assert expected_dir.is_dir()

    expected_file = expected_dir / "data.xml"
    assert expected_file.exists()
    assert expected_file.read_bytes() == b"<data />"
    assert path == os.fspath(expected_file)


def test_store_xml_to_disk_rejects_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(xml_download, "get_settings", lambda: SimpleNamespace(xml_storage_root=tmp_path))

    with pytest.raises(ValueError):
        xml_download.store_xml_to_disk("/../../etc/passwd", b"<data />")
