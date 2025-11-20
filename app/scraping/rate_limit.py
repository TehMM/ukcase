"""Rate limiting helpers for scraping operations."""
from __future__ import annotations

import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from app.config import get_settings

if TYPE_CHECKING:  # pragma: no cover
    from app.db.models import Segment
else:  # pragma: no cover
    Segment = Any


def _coerce_rate_limit(value: Optional[Decimal | float | int]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_rate_limit_seconds(segment: Segment) -> float:
    """Return the rate limit in seconds for a segment, falling back to defaults."""

    settings = get_settings()
    segment_value = _coerce_rate_limit(getattr(segment, "rate_limit_seconds", None))
    return segment_value if segment_value is not None else settings.default_rate_limit_seconds


def respect_rate_limit(segment: Segment) -> None:
    """Sleep for the configured rate limit for the provided segment."""

    sleep_seconds = get_rate_limit_seconds(segment)
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
