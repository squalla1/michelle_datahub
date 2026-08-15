"""Fetched-content query endpoints.

Two shapes:
- `GET /api/v1/content` — generic cross-module query (filters + paging).
- `GET /api/v1/content/{module}` — per-type feed; defaults to *today's* items and
  returns the latest N. `{module}` is one of the 9 module keys (news, events,
  calendar, company, market, macro, opinion, channel, person).
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...catalog import MODULES
from ...models import ContentItem
from ...schemas import ContentItemOut
from ..deps import get_session

router = APIRouter(prefix="/api/v1/content", tags=["content"])

_MODULE_KEYS = {m.key.value for m in MODULES}


def _date_column(by: str, param: str = "by"):
    """Pick which timestamp the `date` filter and ordering apply to.

    `published` = when the item was published by the source (semantic date, but
    null for sources that carry no timestamp, e.g. scraped links);
    `fetched` = when we ingested it (always present)."""
    if by == "fetched":
        return ContentItem.fetched_at
    if by == "published":
        return ContentItem.published_at
    raise HTTPException(422, detail=f"{param} must be 'published' or 'fetched'")


def _event_window(stmt, event_from: date_cls | None, event_to: date_cls | None):
    """Filter on `payload.event_date` — the *scheduled* date of a calendar item,
    which is what a calendar page pages through (published_at mirrors it, but
    payload is where the source's own string lives, sometimes with a time part).
    Values are ISO, so the first 10 characters compare as dates."""
    if event_from is None and event_to is None:
        return stmt
    day = func.substr(ContentItem.payload["event_date"].as_string(), 1, 10)
    stmt = stmt.where(ContentItem.payload["event_date"].as_string().isnot(None))
    if event_from is not None:
        stmt = stmt.where(day >= event_from.isoformat())
    if event_to is not None:
        stmt = stmt.where(day <= event_to.isoformat())
    return stmt


def _day_bounds(day: date_cls) -> tuple[datetime, datetime]:
    """[00:00, next-day 00:00) in UTC for a calendar date."""
    start = datetime.combine(day, time.min)
    return start, start + timedelta(days=1)


@router.get("", response_model=list[ContentItemOut])
def list_content(
    module: str | None = None,
    source_id: int | None = None,
    date: date_cls | None = Query(None, description="calendar day (UTC) to filter, e.g. 2026-06-22"),
    by: str = Query("published", description="date field the `date` filter applies to: 'published' or 'fetched'"),
    order: str = Query("fetched", description="sort field: 'fetched' (default) or 'published'"),
    since: datetime | None = Query(None, description="filter published_at >= since"),
    event_from: date_cls | None = Query(None, description="calendar items with payload.event_date >= this day"),
    event_to: date_cls | None = Query(None, description="calendar items with payload.event_date <= this day"),
    q: str | None = Query(None, description="substring match on title"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = 0,
    session: Session = Depends(get_session),
) -> list[ContentItem]:
    col = _date_column(by)
    sort_col = _date_column(order, "order")
    stmt = select(ContentItem)
    if module:
        stmt = stmt.where(ContentItem.module == module)
    if source_id:
        stmt = stmt.where(ContentItem.source_id == source_id)
    stmt = _event_window(stmt, event_from, event_to)
    if date is not None:
        start, end = _day_bounds(date)
        stmt = stmt.where(col >= start, col < end)
    if since:
        stmt = stmt.where(ContentItem.published_at >= since)
    if q:
        stmt = stmt.where(ContentItem.title.ilike(f"%{q}%"))
    # `id desc` is the tiebreaker: a whole batch (e.g. one day's treasury curve)
    # lands with the same fetched_at, and without it the batch order is arbitrary
    # — the newest snapshot would not reliably come first.
    stmt = (
        stmt.order_by(sort_col.desc().nullslast(), ContentItem.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(session.scalars(stmt))


@router.get("/{module}", response_model=list[ContentItemOut])
def list_module_content(
    module: str,
    date: date_cls | None = Query(None, description="calendar day (UTC); defaults to today"),
    by: str = Query("published", description="date field: 'published' or 'fetched'"),
    event_from: date_cls | None = Query(None, description="calendar items with payload.event_date >= this day"),
    event_to: date_cls | None = Query(None, description="calendar items with payload.event_date <= this day"),
    q: str | None = Query(None, description="substring match on title"),
    limit: int = Query(50, ge=1, le=500, description="return the latest N items"),
    offset: int = 0,
    session: Session = Depends(get_session),
) -> list[ContentItem]:
    """Latest N items of one module type for a given day (default: today, UTC).

    Pass `date=` to page back through history, or `limit=` to cap the response
    for efficiency. Ordering is newest-first on the chosen `by` field.

    When `date` is omitted and today's window is empty (low-frequency modules —
    calendar/macro/market — can go days without new items, and dedup never
    updates `fetched_at`), the endpoint falls back to the latest N items overall
    instead of returning `[]`. An explicit `date=` never falls back.

    `event_from`/`event_to` select calendar items by their scheduled date
    (`payload.event_date`) and, being a window of their own, switch off the
    single-day default; results then come back in ascending event order, which
    is how a schedule reads."""
    if module not in _MODULE_KEYS:
        raise HTTPException(404, detail=f"unknown module '{module}'; one of {sorted(_MODULE_KEYS)}")
    col = _date_column(by)
    day = date or datetime.now(timezone.utc).date()
    start, end = _day_bounds(day)
    by_event = event_from is not None or event_to is not None

    def _query(day_bounded: bool):
        stmt = select(ContentItem).where(ContentItem.module == module)
        if day_bounded:
            stmt = stmt.where(col >= start, col < end)
        if q:
            stmt = stmt.where(ContentItem.title.ilike(f"%{q}%"))
        stmt = _event_window(stmt, event_from, event_to)
        if by_event:
            order = func.substr(ContentItem.payload["event_date"].as_string(), 1, 10).asc()
        else:
            order = col.desc() if day_bounded else col.desc().nullslast()
        stmt = stmt.order_by(order, ContentItem.id.desc()).offset(offset).limit(limit)
        return list(session.scalars(stmt))

    if by_event:
        return _query(day_bounded=date is not None)
    items = _query(day_bounded=True)
    if not items and date is None:
        items = _query(day_bounded=False)
    return items
