"""Admin HTML routes for managing segments and runs."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db import crud
from app.db.crud import RunNotFoundError
from app.scraping import pipeline
from app.web.auth import get_current_admin
from app.web.deps import get_db
from app.web.templates import templates

router = APIRouter()


@router.get("/", response_class=RedirectResponse)
def root() -> RedirectResponse:
    return RedirectResponse(url="/admin/segments", status_code=status.HTTP_302_FOUND)


@router.get("/admin/segments", response_class=HTMLResponse)
def segments_index(
    request: Request,
    db: Session = Depends(get_db),
    _: str = Depends(get_current_admin),
) -> HTMLResponse:
    segments = crud.list_segments(db)
    return templates.TemplateResponse(
        "segments.html",
        {
            "request": request,
            "segments": segments,
        },
    )


@router.post("/admin/segments/{segment_id}/run/backfill", response_class=HTMLResponse)
def run_backfill(
    request: Request,
    segment_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(get_current_admin),
) -> HTMLResponse:
    _segment = crud.get_segment_by_id(db, segment_id)
    if _segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")

    result = pipeline.run_backfill_for_segment(segment_id)
    return templates.TemplateResponse(
        "partials/run_result.html",
        {
            "request": request,
            "result": result,
        },
    )


@router.post("/admin/segments/{segment_id}/run/incremental", response_class=HTMLResponse)
def run_incremental(
    request: Request,
    segment_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(get_current_admin),
) -> HTMLResponse:
    _segment = crud.get_segment_by_id(db, segment_id)
    if _segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")

    result = pipeline.run_incremental_for_segment(segment_id)
    return templates.TemplateResponse(
        "partials/run_result.html",
        {
            "request": request,
            "result": result,
        },
    )


@router.get("/admin/runs", response_class=HTMLResponse)
def runs_index(
    request: Request,
    db: Session = Depends(get_db),
    _: str = Depends(get_current_admin),
) -> HTMLResponse:
    runs = crud.list_recent_runs(db, limit=50)
    return templates.TemplateResponse(
        "runs.html",
        {
            "request": request,
            "runs": runs,
        },
    )


@router.get("/admin/runs/{run_id}", response_class=HTMLResponse)
def run_detail(
    run_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: str = Depends(get_current_admin),
) -> HTMLResponse:
    try:
        run, items = crud.get_run_with_items(db, run_id)
    except RunNotFoundError as exc:  # pragma: no cover - defensive, covered in tests via exception path
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return templates.TemplateResponse(
        "run_detail.html",
        {
            "request": request,
            "run": run,
            "items": items,
        },
    )
