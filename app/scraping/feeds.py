"""Atom feed construction and parsing utilities."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, List, Optional
from urllib.parse import urlencode, urljoin, urlsplit

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional, TYPE_CHECKING
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

    query_params = {}
    query_value = getattr(segment, "query", None)
    if query_value:
        query_params["query"] = query_value

    decision_date_from = getattr(segment, "decision_date_from", None)
    decision_date_to = getattr(segment, "decision_date_to", None)
    if decision_date_from is not None:
        query_params["decision_date_from"] = decision_date_from.isoformat()
    if decision_date_to is not None:
        query_params["decision_date_to"] = decision_date_to.isoformat()

    courts = getattr(segment, "courts", None) or []

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
    """Convert a feedparser time.struct_time into a naive datetime.

    We reconstruct the datetime directly from the struct fields to avoid
    local timezone conversion via time.mktime(), which can introduce
    timezone-dependent offsets.
    """

    if value is None:
        return None
    return datetime(
        value.tm_year,
        value.tm_mon,
        value.tm_mday,
        value.tm_hour,
        value.tm_min,
        value.tm_sec,
    )


def _fetch_atom_feed(url: str) -> str:
    """Fetch an Atom feed from the given URL with simple retry behaviour.

    Retries are only performed for HTTP 429 and 5xx responses, or for
    network-level errors raised by httpx. Other 4xx responses raise
    immediately without retry.
    """
    settings = get_settings()
    timeout = settings.request_timeout_seconds
    max_retries = settings.max_http_retries
    last_exception: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            response = httpx.get(
                url,
                timeout=timeout,
                headers={"User-Agent": settings.http_user_agent},
            )
            status = response.status_code

            if status == httpx.codes.OK:
                return response.text

            # Retry on "Too Many Requests" and 5xx responses.
            if status == getattr(httpx.codes, "TOO_MANY_REQUESTS", 429) or 500 <= status < 600:
                last_exception = httpx.HTTPStatusError(
                    f"Unexpected status code {status}",
                    request=response.request,
                    response=response,
                )
            else:
                # Non-retryable client error: raise immediately.
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # noqa: BLE001 - controlled re-raise for client errors
            status_code = getattr(exc.response, "status_code", None)
            if status_code is not None and status_code < 500 and status_code != getattr(httpx.codes, "TOO_MANY_REQUESTS", 429):
                raise
            last_exception = exc
        except Exception as exc:  # noqa: BLE001 - we deliberately capture all other errors to retry
            last_exception = exc

        # Lightweight backoff between retry attempts.
        sleep_for = min(5.0, 0.5 * attempt)
        time.sleep(sleep_for)

    if last_exception is not None:
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
