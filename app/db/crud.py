from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Judgment
from app.scraping.xml_parse import JudgmentMetadata


def get_judgment_by_canonical_uri(session: Session, canonical_uri: str) -> Optional[Judgment]:
    """Return a Judgment by canonical_uri, or None if not found."""

    statement = select(Judgment).where(Judgment.canonical_uri == canonical_uri)
    return session.execute(statement).scalar_one_or_none()


def create_judgment_from_metadata(
    session: Session,
    *,
    canonical_uri: str,
    metadata: JudgmentMetadata,
    xml_path: str,
    first_seen_segment_id: Optional[int] = None,
) -> Judgment:
    """Create and persist a new Judgment row based on parsed metadata."""

    now = datetime.now(timezone.utc)
    judgment = Judgment(
        canonical_uri=canonical_uri,
        neutral_citation=metadata.neutral_citation,
        neutral_citation_number=metadata.neutral_citation_number,
        court_code=metadata.court_code,
        decision_date=metadata.decision_date,
        title=metadata.title,
        parties=metadata.parties,
        judge=metadata.judge,
        xml_path=xml_path,
        xml_downloaded_at=now,
        status="DOWNLOADED",
        first_seen_segment_id=first_seen_segment_id,
        first_seen_at=now,
        rag_status="NOT_PROCESSED",
    )

    session.add(judgment)
    session.flush()
    return judgment
