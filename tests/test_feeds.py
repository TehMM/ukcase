from datetime import datetime
from types import SimpleNamespace
import pathlib
import sys
import types
import xml.etree.ElementTree as ET
import textwrap

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # Ensure the repository root is importable for local app modules
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

# Provide lightweight stubs when dependencies are unavailable in the test environment.
try:  # pragma: no cover - only executed if dependency already installed
    import httpx  # type: ignore
except ImportError:  # pragma: no cover
    httpx = types.ModuleType("httpx")

    class Response:
        def __init__(self, status_code: int, text: str, request=None):
            self.status_code = status_code
            self.text = text
            self.request = request

        def raise_for_status(self):
            if self.status_code >= 400:
                raise HTTPStatusError(f"status {self.status_code}", request=self.request, response=self)

    class HTTPStatusError(Exception):
        def __init__(self, message: str, request=None, response=None):
            super().__init__(message)
            self.request = request
            self.response = response

    class Codes(SimpleNamespace):
        OK = 200
        TOO_MANY_REQUESTS = 429
        NOT_FOUND = 404
        SERVICE_UNAVAILABLE = 503

    httpx.Response = Response
    httpx.HTTPStatusError = HTTPStatusError
    httpx.codes = Codes()

    def _missing_get(*args, **kwargs):  # pragma: no cover - replaced in tests
        raise RuntimeError("httpx.get stub called without monkeypatch")

    httpx.get = _missing_get
    sys.modules["httpx"] = httpx

try:  # pragma: no cover
    import feedparser  # type: ignore
except ImportError:  # pragma: no cover
    feedparser = types.ModuleType("feedparser")

    def _parse(xml_text: str):
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(textwrap.dedent(xml_text).strip())
        entries = []
        for elem in root.findall("atom:entry", ns):
            entry = {}
            id_elem = elem.find("atom:id", ns)
            link_elem = elem.find("atom:link", ns)
            title_elem = elem.find("atom:title", ns)
            updated_elem = elem.find("atom:updated", ns)
            published_elem = elem.find("atom:published", ns)
            if id_elem is not None and id_elem.text:
                entry["id"] = id_elem.text
            if link_elem is not None:
                entry["link"] = link_elem.attrib.get("href")
            if title_elem is not None and title_elem.text:
                entry["title"] = title_elem.text
            if updated_elem is not None and updated_elem.text:
                entry["updated_parsed"] = datetime.strptime(updated_elem.text, "%Y-%m-%dT%H:%M:%SZ").timetuple()
            if published_elem is not None and published_elem.text:
                entry["published_parsed"] = datetime.strptime(published_elem.text, "%Y-%m-%dT%H:%M:%SZ").timetuple()
            entries.append(entry)
        return SimpleNamespace(entries=entries)

    feedparser.parse = _parse
    sys.modules["feedparser"] = feedparser

import httpx  # type: ignore  # noqa: E402  # ensures stub is used if necessary
import pytest

from app.scraping import feeds


@pytest.fixture(autouse=True)
def _mock_settings(monkeypatch):
    fake_settings = SimpleNamespace(
        request_timeout_seconds=5,
        max_http_retries=2,
        default_rate_limit_seconds=1.5,
        http_user_agent="test-agent",
    )
    monkeypatch.setattr(feeds, "get_settings", lambda: fake_settings)


def test_build_atom_url_with_query_and_courts():
    segment = SimpleNamespace(query="fiduciary", courts=["ewhc/ch", "ewhc/comm"], raw_atom_url=None)

    url = feeds.build_atom_url_for_segment(segment)

    assert url == (
        "https://caselaw.nationalarchives.gov.uk/atom.xml?"
        "query=fiduciary&court=ewhc%2Fch&court=ewhc%2Fcomm"
    )


def test_build_atom_url_raw_override():
    segment = SimpleNamespace(raw_atom_url="https://example.com/custom.atom")

    assert feeds.build_atom_url_for_segment(segment) == "https://example.com/custom.atom"


@pytest.fixture
def sample_atom_xml():
    return """
        <?xml version="1.0" encoding="utf-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
            <title>Sample feed</title>
            <entry>
                <id>https://caselaw.nationalarchives.gov.uk/ewhc/comm/2025/3036</id>
                <title>Example Case</title>
                <updated>2025-02-01T00:00:00Z</updated>
                <published>2025-01-31T00:00:00Z</published>
                <link href="https://caselaw.nationalarchives.gov.uk/ewhc/comm/2025/3036" />
            </entry>
        </feed>
    """


def test_fetch_atom_entries_parses_sample(monkeypatch, sample_atom_xml):
    def fake_get(url: str, headers=None, timeout: int | None = None):
        return httpx.Response(status_code=200, text=sample_atom_xml)

    monkeypatch.setattr(feeds.httpx, "get", fake_get)

    segment = SimpleNamespace()
    entries = feeds.fetch_atom_entries(segment)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.canonical_uri == "/ewhc/comm/2025/3036"
    assert entry.link == "https://caselaw.nationalarchives.gov.uk/ewhc/comm/2025/3036"
    assert entry.title == "Example Case"
    assert entry.updated == datetime(2025, 2, 1, 0, 0)
    assert entry.published == datetime(2025, 1, 31, 0, 0)
    assert entry.xml_url == "https://caselaw.nationalarchives.gov.uk/ewhc/comm/2025/3036/data.xml"


def test_derive_xml_url_handles_missing_leading_slash():
    assert (
        feeds.derive_xml_url("ewhc/comm/2025/3036")
        == "https://caselaw.nationalarchives.gov.uk/ewhc/comm/2025/3036/data.xml"
    )


def test_parse_datetime_preserves_utc():
    import time as _time

    parsed = feeds._parse_datetime(_time.struct_time((2025, 1, 2, 15, 45, 30, 0, 0, 0)))

    assert parsed == datetime(2025, 1, 2, 15, 45, 30)


def test_fetch_atom_feed_retries_on_server_error(monkeypatch):
    sleep_calls: list[float] = []
    calls = {"count": 0}

    def fake_get(url: str, timeout: int, headers: dict):
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(status_code=500, text="server error")
        return httpx.Response(status_code=200, text="<feed />")

    monkeypatch.setattr(feeds.httpx, "get", fake_get)
    monkeypatch.setattr(feeds.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    text = feeds._fetch_atom_feed("https://example.com/atom.xml")

    assert text == "<feed />"
    assert calls["count"] == 2
    assert len(sleep_calls) == 1


def test_fetch_atom_feed_raises_on_not_found(monkeypatch):
    sleep_calls: list[float] = []

    def fake_get(url: str, timeout: int, headers: dict):
        return httpx.Response(status_code=404, text="not found")

    monkeypatch.setattr(feeds.httpx, "get", fake_get)
    monkeypatch.setattr(feeds.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    with pytest.raises(httpx.HTTPStatusError):
        feeds._fetch_atom_feed("https://example.com/missing.atom")

    assert sleep_calls == []
