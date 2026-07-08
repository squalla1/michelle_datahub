"""FastAPI application factory."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ..config import get_settings
from ..storage import init_db
from .routes import content, jobs, modules, monitor, sources

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
        description=(
            "Multi-source intelligence data hub: news, global events, calendars, "
            "company, market and macro data from 1200+ sources — scheduled fetching, "
            "dedup storage, per-type daily feeds. "
            "多源情报数据中台:定时抓取、排重入库,按类型提供每日数据接口。"
        ),
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
    app.include_router(monitor.router)
    return app


app = create_app()
