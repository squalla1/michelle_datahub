"""Scheduler control + catalog reload endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from ...ingest.catalog_ingest import ingest_catalog
from ...scheduler import scheduler_service

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("")
def list_jobs() -> dict:
    return {"running": scheduler_service.scheduler.running, "jobs": scheduler_service.jobs()}


@router.post("/reload")
def reload_jobs() -> dict:
    """Rebuild scheduler jobs from the current catalog state."""
    counts = scheduler_service.load_jobs()
    return {"reloaded": True, "by_kind": counts, "total_jobs": len(scheduler_service.jobs())}


@router.post("/catalog/reload")
def reload_catalog() -> dict:
    """Re-parse the Excel registry into the catalog, then rebuild jobs."""
    summary = ingest_catalog()
    scheduler_service.load_jobs()
    return {"catalog": summary, "total_jobs": len(scheduler_service.jobs())}
