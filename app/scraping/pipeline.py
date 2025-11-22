"""Segment-level scraping pipeline for backfill and incremental runs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db import crud
from app.db.base import SessionLocal
from app.db.models import Judgment, Run, RunType, Segment
from app.scraping.feeds import AtomEntry, build_atom_url_for_segment, fetch_atom_entries
from app.scraping.rate_limit import respect_rate_limit
from app.scraping.xml_download import download_xml_for_canonical_uri, store_xml_to_disk
from app.scraping.xml_parse import MetadataParseError, parse_judgment_metadata_from_xml


@dataclass
class SegmentRunResult:
    run: Run
    total_entries: int
    new_judgments: int
    skipped_existing: int
    failed_items: int


def filter_entries_for_run_type(
    session: Session,
    run_type: RunType,
    entries: list[AtomEntry],
) -> list[AtomEntry]:
    """Filter Atom entries based on run type.

    BACKFILL: return all entries.
    INCREMENTAL: return only entries whose canonical_uri does not yet exist in Judgment.
    """

    if run_type == RunType.BACKFILL:
        return entries

    filtered: list[AtomEntry] = []
    for entry in entries:
        existing: Optional[Judgment] = crud.get_judgment_by_canonical_uri(
            session, entry.canonical_uri
        )
        if existing is None:
            filtered.append(entry)
    return filtered


def process_entry_for_run(
    session: Session,
    run: Run,
    segment: Segment,
    entry: AtomEntry,
) -> None:
    """Process a single Atom entry within a run."""

    canonical_uri = entry.canonical_uri
    if not canonical_uri or not canonical_uri.startswith("/"):
        item = crud.create_run_item(
            session, run=run, canonical_uri=canonical_uri or "", xml_url=entry.xml_url
        )
        crud.mark_run_item_failure(
            session, item, error_message="Invalid canonical_uri"
        )
        run.failed_items += 1
        run.total_entries += 1
        return

    # Re-check even after incremental filtering to guard against concurrent inserts
    # or changes since the initial filter.
    existing = crud.get_judgment_by_canonical_uri(session, canonical_uri)
    if existing is not None:
        item = crud.create_run_item(
            session, run=run, canonical_uri=canonical_uri, xml_url=entry.xml_url
        )
        crud.mark_run_item_skipped_existing(session, item, judgment_id=existing.id)
        run.skipped_existing += 1
        run.total_entries += 1
        return

    item = crud.create_run_item(
        session, run=run, canonical_uri=canonical_uri, xml_url=entry.xml_url
    )
    try:
        respect_rate_limit(segment)
        _, xml_bytes = download_xml_for_canonical_uri(canonical_uri)
        xml_path = store_xml_to_disk(canonical_uri, xml_bytes)
        metadata = parse_judgment_metadata_from_xml(xml_bytes)
        judgment = crud.create_judgment_from_metadata(
            session,
            canonical_uri=canonical_uri,
            metadata=metadata,
            xml_path=xml_path,
            first_seen_segment_id=segment.id,
        )
        crud.mark_run_item_success(
            session, item, xml_path=xml_path, judgment_id=judgment.id
        )
        run.new_judgments += 1
        run.total_entries += 1
    except MetadataParseError as exc:
        crud.mark_run_item_failure(
            session, item, error_message=f"MetadataParseError: {exc}"
        )
        run.failed_items += 1
        run.total_entries += 1
    except Exception as exc:  # noqa: BLE001 - deliberate catch-all per item
        crud.mark_run_item_failure(
            session, item, error_message=f"Unexpected error: {exc}"
        )
        run.failed_items += 1
        run.total_entries += 1


def run_segment(
    segment_id: int,
    run_type: RunType,
    max_entries: Optional[int] = None,
) -> SegmentRunResult:
    """Execute a scraping run for a given segment."""

    with SessionLocal() as session:
        segment = session.get(Segment, segment_id)
        if segment is None:
            raise ValueError(f"Segment {segment_id} not found")

        run = crud.create_run(session, segment=segment, run_type=run_type)
        session.commit()

        try:
            atom_url = build_atom_url_for_segment(segment)
            entries = fetch_atom_entries(atom_url)
            filtered_entries = filter_entries_for_run_type(session, run_type, entries)

            if run_type == RunType.INCREMENTAL:
                filtered_uris = {entry.canonical_uri for entry in filtered_entries}
                for entry in entries:
                    if entry.canonical_uri in filtered_uris:
                        continue

                    existing = crud.get_judgment_by_canonical_uri(
                        session, entry.canonical_uri
                    )
                    if existing is None:
                        filtered_entries.append(entry)
                        continue

                    item = crud.create_run_item(
                        session,
                        run=run,
                        canonical_uri=entry.canonical_uri,
                        xml_url=entry.xml_url,
                    )
                    crud.mark_run_item_skipped_existing(
                        session, item, judgment_id=existing.id
                    )
                    run.skipped_existing += 1
                    run.total_entries += 1
                    session.commit()

            if max_entries is not None:
                filtered_entries = filtered_entries[:max_entries]

            for entry in filtered_entries:
                process_entry_for_run(session, run, segment, entry)
                session.commit()

            crud.mark_run_success(session, run)
            session.commit()
        except Exception as exc:
            crud.mark_run_failure(session, run, exc)
            session.commit()
            raise

        return SegmentRunResult(
            run=run,
            total_entries=run.total_entries,
            new_judgments=run.new_judgments,
            skipped_existing=run.skipped_existing,
            failed_items=run.failed_items,
        )


def run_backfill_for_segment(
    segment_id: int,
    max_entries: Optional[int] = None,
) -> SegmentRunResult:
    return run_segment(segment_id, RunType.BACKFILL, max_entries=max_entries)


def run_incremental_for_segment(segment_id: int) -> SegmentRunResult:
    return run_segment(segment_id, RunType.INCREMENTAL, max_entries=None)
