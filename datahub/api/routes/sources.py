"""Catalog source endpoints + on-demand fetch trigger."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...ingest.runner import run_source
from ...models import DataSource, FetchRun
from ...schemas import DataSourceOut, FetchRunOut
from ..deps import get_session

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])


@router.get("", response_model=list[DataSourceOut])
def list_sources(
    module: str | None = None,
    priority: str | None = None,
    method: str | None = None,
    enabled: bool | None = None,
    q: str | None = Query(None, description="substring match on name"),
    limit: int = Query(100, le=1000),
    offset: int = 0,
    session: Session = Depends(get_session),
) -> list[DataSource]:
    stmt = select(DataSource)
    if module:
        stmt = stmt.where(DataSource.module == module)
    if priority:
        stmt = stmt.where(DataSource.priority == priority)
    if method:
        stmt = stmt.where(DataSource.method.ilike(f"%{method}%"))
    if enabled is not None:
        stmt = stmt.where(DataSource.enabled.is_(enabled))
    if q:
        stmt = stmt.where(DataSource.name.ilike(f"%{q}%"))
    stmt = stmt.order_by(DataSource.id).offset(offset).limit(limit)
    return list(session.scalars(stmt))


@router.get("/{source_id}", response_model=DataSourceOut)
def get_source(source_id: int, session: Session = Depends(get_session)) -> DataSource:
    src = session.get(DataSource, source_id)
    if src is None:
        raise HTTPException(404, "source not found")
    return src


@router.post("/{source_id}/fetch")
def fetch_now(source_id: int) -> dict:
    """Trigger an immediate synchronous fetch for one source."""
    summary = run_source(source_id)
    if summary.get("error") == "source not found":
        raise HTTPException(404, "source not found")
    return summary


@router.get("/{source_id}/runs", response_model=list[FetchRunOut])
def source_runs(
    source_id: int, limit: int = Query(20, le=200), session: Session = Depends(get_session)
) -> list[FetchRun]:
    stmt = (
        select(FetchRun)
        .where(FetchRun.source_id == source_id)
        .order_by(FetchRun.id.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))
