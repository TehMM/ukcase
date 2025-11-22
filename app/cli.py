from datetime import date
from typing import Optional

import typer

from app.db import crud
from app.db.base import SessionLocal
from app.db.models import RunType
from app.scraping import pipeline

app = typer.Typer(help="ukcase: UK caselaw scraper CLI.")
segment_app = typer.Typer(help="Manage segments.")
run_app = typer.Typer(help="Run scrapes for segments.")

app.add_typer(segment_app, name="segment")
app.add_typer(run_app, name="run")


def _parse_date(value: Optional[str]) -> Optional[date]:
    if value is None:
        return None
    return date.fromisoformat(value)


@segment_app.command("list")
def segment_list() -> None:
    """List all segments."""

    with SessionLocal() as session:
        segments = crud.list_segments(session)
        if not segments:
            typer.echo("No segments.")
            raise typer.Exit(code=0)
        for seg in segments:
            typer.echo(
                f"[{seg.id}] {seg.name} (active={seg.is_active}, "
                f"query={seg.query!r}, courts={seg.courts})"
            )


@segment_app.command("create")
def segment_create(
    name: str = typer.Argument(..., help="Unique name for the segment."),
    query: Optional[str] = typer.Option(None, help="Keyword query for TNA search."),
    court: list[str] = typer.Option(
        None,
        "--court",
        help="Court code(s) (can be repeated), e.g. 'ewhc/ch', 'ewhc/comm'.",
    ),
    decision_date_from: Optional[str] = typer.Option(
        None, help="Decision date from (YYYY-MM-DD)."
    ),
    decision_date_to: Optional[str] = typer.Option(
        None, help="Decision date to (YYYY-MM-DD)."
    ),
    backfill_mode: str = typer.Option(
        "NEW_ONLY", help="Backfill mode, e.g. NEW_ONLY or FULL_HISTORY."
    ),
    rate_limit_seconds: float = typer.Option(
        1.5, help="Per-request rate limit in seconds."
    ),
    is_active: bool = typer.Option(True, help="Whether this segment is active."),
) -> None:
    """Create a new segment."""

    with SessionLocal() as session:
        existing = crud.get_segment_by_name(session, name)
        if existing is not None:
            typer.echo(f"Segment named {name!r} already exists.", err=True)
            raise typer.Exit(code=1)

        segment = crud.create_segment(
            session,
            name=name,
            query=query,
            courts=court or None,
            decision_date_from=_parse_date(decision_date_from),
            decision_date_to=_parse_date(decision_date_to),
            backfill_mode=backfill_mode,
            rate_limit_seconds=rate_limit_seconds,
            is_active=is_active,
        )
        session.commit()
        typer.echo(f"Created segment [{segment.id}] {segment.name}")


@segment_app.command("show")
def segment_show(segment_id: int = typer.Argument(..., help="Segment ID.")) -> None:
    """Display details for a segment."""

    with SessionLocal() as session:
        segment = crud.get_segment_by_id(session, segment_id)
        if segment is None:
            typer.echo(f"Segment {segment_id} not found.", err=True)
            raise typer.Exit(code=1)
        typer.echo(
            f"Segment {segment.id}: {segment.name}\n"
            f"  description: {segment.description}\n"
            f"  query: {segment.query}\n"
            f"  courts: {segment.courts}\n"
            f"  decision_date_from: {segment.decision_date_from}\n"
            f"  decision_date_to: {segment.decision_date_to}\n"
            f"  backfill_mode: {segment.backfill_mode}\n"
            f"  rate_limit_seconds: {segment.rate_limit_seconds}\n"
            f"  is_active: {segment.is_active}"
        )


@segment_app.command("update")
def segment_update(
    segment_id: int = typer.Argument(..., help="Segment ID."),
    query: Optional[str] = typer.Option(None, help="Updated query value."),
    court: list[str] = typer.Option(None, "--court", help="Court code(s)."),
    decision_date_from: Optional[str] = typer.Option(None, help="YYYY-MM-DD."),
    decision_date_to: Optional[str] = typer.Option(None, help="YYYY-MM-DD."),
    backfill_mode: Optional[str] = typer.Option(None, help="Backfill mode."),
    rate_limit_seconds: Optional[float] = typer.Option(
        None, help="Per-request rate limit in seconds."
    ),
    is_active: Optional[bool] = typer.Option(None, help="Whether the segment is active."),
) -> None:
    """Update fields on an existing segment."""

    with SessionLocal() as session:
        segment = crud.get_segment_by_id(session, segment_id)
        if segment is None:
            typer.echo(f"Segment {segment_id} not found.", err=True)
            raise typer.Exit(code=1)

        updates: dict[str, object] = {}
        if query is not None:
            updates["query"] = query
        if court:
            updates["courts"] = court
        if decision_date_from is not None:
            updates["decision_date_from"] = _parse_date(decision_date_from)
        if decision_date_to is not None:
            updates["decision_date_to"] = _parse_date(decision_date_to)
        if backfill_mode is not None:
            updates["backfill_mode"] = backfill_mode
        if rate_limit_seconds is not None:
            updates["rate_limit_seconds"] = rate_limit_seconds
        if is_active is not None:
            updates["is_active"] = is_active

        crud.update_segment(session, segment, **updates)
        session.commit()
        typer.echo(f"Updated segment [{segment.id}] {segment.name}")


@segment_app.command("delete")
def segment_delete(segment_id: int = typer.Argument(..., help="Segment ID.")) -> None:
    """Delete a segment."""

    with SessionLocal() as session:
        segment = crud.get_segment_by_id(session, segment_id)
        if segment is None:
            typer.echo(f"Segment {segment_id} not found.", err=True)
            raise typer.Exit(code=1)

        crud.delete_segment(session, segment)
        session.commit()
        typer.echo(f"Deleted segment {segment_id}")


@run_app.command("backfill")
def run_backfill(
    segment_id: int = typer.Argument(..., help="Segment ID."),
    max_entries: Optional[int] = typer.Option(
        None, help="Optional maximum number of Atom entries to process."
    ),
) -> None:
    """Run a backfill scrape for a segment."""

    result = pipeline.run_backfill_for_segment(segment_id, max_entries=max_entries)
    typer.echo(
        f"Run {result.run.id} BACKFILL for segment {segment_id}: "
        f"total={result.total_entries}, "
        f"new={result.new_judgments}, "
        f"skipped={result.skipped_existing}, "
        f"failed={result.failed_items}, "
        f"status={result.run.status}"
    )


@run_app.command("incremental")
def run_incremental(
    segment_id: int = typer.Argument(..., help="Segment ID."),
) -> None:
    """Run an incremental scrape for a segment."""

    result = pipeline.run_incremental_for_segment(segment_id)
    typer.echo(
        f"Run {result.run.id} INCREMENTAL for segment {segment_id}: "
        f"total={result.total_entries}, "
        f"new={result.new_judgments}, "
        f"skipped={result.skipped_existing}, "
        f"failed={result.failed_items}, "
        f"status={result.run.status}"
    )


if __name__ == "__main__":
    app()
