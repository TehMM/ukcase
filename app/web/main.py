"""FastAPI application factory for the ukcase admin UI and webhook endpoints."""
from fastapi import FastAPI

from app.web.routes_admin import router as admin_router
from app.web.routes_webhook import router as webhook_router


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(title="ukcase admin")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(admin_router)
    app.include_router(webhook_router)

    return app
