from __future__ import annotations

import logging
import os
import time
from typing import Optional, Tuple

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.scraping.feeds import derive_xml_url

logger = logging.getLogger(__name__)


def download_xml_for_canonical_uri(
    canonical_uri: str,
    *,
    session: Optional[Session] = None,
) -> Tuple[str, bytes]:
    """Download the XML for a canonical URI with retry and backoff.

    Retries are performed only for HTTP 429 and 5xx responses or network-level
    errors raised by httpx. Other 4xx responses raise immediately without
    retry. The optional SQLAlchemy ``session`` parameter is reserved for future
    logging but is not used yet.
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
                logger.debug("Retryable status %s for %s", status, canonical_uri)
            else:
                response.raise_for_status()

        except httpx.HTTPStatusError as exc:  # noqa: BLE001 - propagate non-retryable client errors
            status_code = getattr(exc.response, "status_code", None)
            if status_code is not None and status_code < 500 and status_code != getattr(httpx.codes, "TOO_MANY_REQUESTS", 429):
                logger.debug("Non-retryable status %s for %s", status_code, canonical_uri)
                raise
            last_exception = exc
        except Exception as exc:  # noqa: BLE001 - deliberate catch-all for retryable failures
            last_exception = exc
            logger.debug("Retrying %s due to error: %s", canonical_uri, exc)

        sleep_for = min(5.0, 0.5 * attempt)
        time.sleep(sleep_for)

    if last_exception is not None:
        logger.error("Failed to fetch XML for %s after %s attempts", canonical_uri, max_retries)
        raise last_exception
    raise RuntimeError("XML fetch failed without an exception")


def store_xml_to_disk(canonical_uri: str, xml_content: bytes) -> str:
    """Persist XML content to disk mirroring the canonical URI structure."""

    settings = get_settings()
    normalized = canonical_uri.lstrip("/")
    base_path = os.fspath(settings.xml_storage_root)
    xml_dir = os.path.join(base_path, normalized)
    os.makedirs(xml_dir, exist_ok=True)

    xml_path = os.path.join(xml_dir, "data.xml")
    tmp_path = f"{xml_path}.tmp"
    with open(tmp_path, "wb") as tmp_file:
        tmp_file.write(xml_content)
    os.replace(tmp_path, xml_path)

    return xml_path
