"""Atom feed construction and parsing utilities."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, List, Optional
from urllib.parse import urlencode, urljoin, urlsplit

import feedparser
import httpx

from app.config import get_settings

if TYPE_CHECKING:  # pragma: no cover - only for type checkers
    from app.db.models import Segment
else:  # pragma: no cover - runtime fallback when ORM dependencies are unavailable
    Segment = Any

BASE_ATOM_URL = "https://caselaw.nationalarchives.gov.uk/atom.xml"
BASE_CANONICAL_PREFIX = "https://caselaw.nationalarchives.gov.uk"

_DEFAULT_HEADERS = {
    "User-Agent": "ukcase-scraper/0.1 (+https://github.com/TehMM/ukcase)",
    "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.8",
}


@dataclass
class AtomEntry:
    """Normalized Atom entry used in the scraping pipeline."""

    canonical_uri: str
    link: str
    title: Optional[str]
    updated: Optional[datetime]
    published: Optional[datetime]

    @property
    def xml_url(self) -> str:
        return derive_xml_url(self.canonical_uri)


def build_atom_url_for_segment(segment: Segment) -> str:
    """Construct the Atom feed URL for a segment following the design spec."""

    # TODO: support party, judge_filter, neutral_citation_filter, date_from, and date_to
    # when the Atom API parameters for these fields are confirmed.
    raw_atom_url = getattr(segment, "raw_atom_url", None)
    if raw_atom_url:
        return raw_atom_url

    query_params = {}
    query_value = getattr(segment, "query", None)
    if query_value:
        query_params["query"] = query_value

    courts = getattr(segment, "courts", None) or []
    # feed expects repeated court params
    encoded_params = []
    if query_params:
        encoded_params.append(urlencode(query_params))
    for court in courts:
        encoded_params.append(urlencode({"court": court}))

    if encoded_params:
        return f"{BASE_ATOM_URL}?{'&'.join(encoded_params)}"
    return BASE_ATOM_URL


def derive_canonical_uri(link: str) -> str:
    """Extract the canonical URI path from a full caselaw URL."""

    parsed = urlsplit(link)
    return parsed.path.rstrip("/")


def derive_xml_url(canonical_uri: str) -> str:
    """Build the XML download URL from a canonical URI path."""

    normalized_path = canonical_uri if canonical_uri.startswith("/") else f"/{canonical_uri}"
    return urljoin(BASE_CANONICAL_PREFIX, f"{normalized_path}/data.xml")


def _parse_datetime(value: Optional[time.struct_time]) -> Optional[datetime]:
    if value is None:
        return None
    return datetime.fromtimestamp(time.mktime(value))


def _fetch_atom_feed(url: str) -> str:
    settings = get_settings()
    timeout = settings.request_timeout_seconds
    max_retries = settings.max_http_retries

    last_exception: Optional[Exception] = None
    backoff = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            response = httpx.get(url, headers=_DEFAULT_HEADERS, timeout=timeout)
            if response.status_code == httpx.codes.OK:
                return response.text
            if response.status_code not in (httpx.codes.TOO_MANY_REQUESTS, httpx.codes.SERVICE_UNAVAILABLE):
                response.raise_for_status()
            last_exception = httpx.HTTPStatusError(
                f"Unexpected status code {response.status_code}", request=response.request, response=response
            )
        except Exception as exc:  # noqa: BLE001 - we want to retry all errors
            last_exception = exc
        if attempt < max_retries:
            time.sleep(backoff)
            backoff *= 2

    if last_exception:
        raise last_exception
    raise RuntimeError("Atom feed fetch failed without an exception")


def fetch_atom_entries(segment: Segment) -> List[AtomEntry]:
    """Fetch Atom entries for a segment using httpx and feedparser."""

    feed_url = build_atom_url_for_segment(segment)
    feed_text = _fetch_atom_feed(feed_url)
    parsed = feedparser.parse(feed_text)

    entries: List[AtomEntry] = []
    for entry in parsed.entries:
        link = entry.get("link") or entry.get("id")
        if not link:
            continue
        canonical_uri = derive_canonical_uri(link)
        entries.append(
            AtomEntry(
                canonical_uri=canonical_uri,
                link=link,
                title=entry.get("title"),
                updated=_parse_datetime(entry.get("updated_parsed")),
                published=_parse_datetime(entry.get("published_parsed")),
            )
        )

    return entries
