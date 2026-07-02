"""FastAPI application factory."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ..config import get_settings
from ..storage import init_db
from .routes import content, jobs, modules, sources

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Start the in-process scheduler unless explicitly disabled (e.g. when the
    # scheduler runs as a separate worker via `datahub schedule`).
    if os.getenv("DATAHUB_API_SCHEDULER", "1") == "1":
        from ..scheduler import scheduler_service

        scheduler_service.load_jobs()
        scheduler_service.start()
        app.state.scheduler = scheduler_service
    yield
    sched = getattr(app.state, "scheduler", None)
    if sched is not None:
        sched.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Michelle DataHub API",
        version="0.1.0",
        description="Catalog-driven ingestion engine for the Michelle data-source registry.",
        lifespan=lifespan,
    )

    @app.get("/health", tags=["health"])
    def health() -> dict:
        s = get_settings()
        return {"status": "ok", "catalog_path": s.catalog_path}

    app.include_router(modules.router)
    app.include_router(sources.router)
    app.include_router(content.router)
    app.include_router(jobs.router)
    return app


app = create_app()
