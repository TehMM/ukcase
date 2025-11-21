from __future__ import annotations

import logging
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
from typing import Optional, Tuple

import httpx

from app.config import get_settings
from app.scraping.feeds import derive_xml_url

logger = logging.getLogger(__name__)


def download_xml_for_canonical_uri(canonical_uri: str) -> Tuple[str, bytes]:
    """Download the XML for a canonical URI with retry and backoff.

    Retries are performed only for HTTP 429 and 5xx responses or network-level
    errors raised by httpx. Other 4xx responses raise immediately without
    retry.
    """

    settings = get_settings()
    xml_url = derive_xml_url(canonical_uri)
    timeout = settings.request_timeout_seconds
    max_retries = settings.max_http_retries
    last_exception: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            logger.debug("Fetching XML for %s (attempt %s)", canonical_uri, attempt)
            response = httpx.get(
                xml_url,
                timeout=timeout,
                headers={"User-Agent": settings.http_user_agent},
            )
            status = response.status_code

            if status == httpx.codes.OK:
                logger.debug("Fetched XML for %s", canonical_uri)
                return xml_url, response.content

            if status == getattr(httpx.codes, "TOO_MANY_REQUESTS", 429) or 500 <= status < 600:
                last_exception = httpx.HTTPStatusError(
                    f"Unexpected status code {status}",
                    request=response.request,
                    response=response,
                )
            else:
                response.raise_for_status()

        except httpx.HTTPStatusError as exc:  # noqa: BLE001 - propagate non-retryable client errors
            status_code = getattr(exc.response, "status_code", None)
            if status_code is not None and status_code < 500 and status_code != getattr(httpx.codes, "TOO_MANY_REQUESTS", 429):
                raise
            last_exception = exc
            logger.warning("Retrying %s due to error: %s", canonical_uri, exc)
        except Exception as exc:  # noqa: BLE001 - deliberate catch-all for retryable failures
            last_exception = exc
            logger.warning("Retrying %s due to error: %s", canonical_uri, exc)

        if attempt < max_retries and last_exception is not None:
            sleep_for = min(5.0, 0.5 * attempt)
            time.sleep(sleep_for)

    if last_exception is not None:
        logger.error("Failed to fetch XML for %s after %s attempts", canonical_uri, max_retries)
        raise last_exception
    raise RuntimeError("XML fetch failed without an exception")


def store_xml_to_disk(canonical_uri: str, xml_content: bytes) -> str:
    """Persist XML content to disk mirroring the canonical URI structure."""

    settings = get_settings()
    parsed = urlsplit(canonical_uri)
    normalized_path = os.path.normpath(parsed.path.lstrip("/"))
    if not normalized_path or normalized_path.startswith(".."):
        raise ValueError("canonical_uri must resolve to a safe relative path")

    base_path = Path(settings.xml_storage_root)
    xml_dir = base_path / normalized_path
    xml_path = xml_dir / "data.xml"

    xml_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = xml_path.with_suffix(".xml.tmp")
    tmp_path.write_bytes(xml_content)
    tmp_path.replace(xml_path)

    return os.fspath(xml_path)
