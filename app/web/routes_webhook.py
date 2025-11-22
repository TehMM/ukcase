"""Webhook endpoints for external integrations."""
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import crud
from app.db.base import SessionLocal
from app.scraping import pipeline

router = APIRouter()


@router.post("/webhook/changedetection")
def webhook_changedetection(
    segment_id: int = Query(...),
    secret: str = Query(...),
):
    settings = get_settings()
    expected = getattr(settings, "changedetection_webhook_secret", None)
    if not expected or secret != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook secret",
        )

    with SessionLocal() as session:
        if crud.get_segment_by_id(session, segment_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Segment not found",
            )

    result = pipeline.run_incremental_for_segment(segment_id)
    return JSONResponse(
        {
            "run_id": result.run.id,
            "segment_id": segment_id,
            "status": result.run.status,
            "total_entries": result.total_entries,
            "new_judgments": result.new_judgments,
            "skipped_existing": result.skipped_existing,
            "failed_items": result.failed_items,
        }
    )
