"""Data-monitoring endpoints: aggregate stats JSON + a self-contained HTML page.

GET /monitor        — dashboard page (inline CSS/JS, fetches /api/v1/stats)
GET /api/v1/stats   — the aggregates powering it
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import ContentItem, DataSource, FetchRun
from ..deps import get_session
from ..monitor_page import MONITOR_HTML

router = APIRouter(tags=["monitor"])


@router.get("/api/v1/stats")
def stats(session: Session = Depends(get_session)) -> dict:
    now = datetime.now(timezone.utc)
    day_start = datetime.combine(now.date(), time.min)
    h24 = now - timedelta(hours=24)

    content_total = session.scalar(select(func.count()).select_from(ContentItem)) or 0
    today_new = session.scalar(
        select(func.count()).where(ContentItem.fetched_at >= day_start)
    ) or 0
    src_total = session.scalar(select(func.count()).select_from(DataSource)) or 0
    src_enabled = session.scalar(
        select(func.count()).where(DataSource.enabled.is_(True))
    ) or 0

    ft_ok = session.scalar(
        select(func.count()).where(ContentItem.fulltext.isnot(None), ContentItem.fulltext != "")
    ) or 0
    ft_fail = session.scalar(select(func.count()).where(ContentItem.fulltext == "")) or 0
    ft_pending = content_total - ft_ok - ft_fail

    runs = dict(
        session.execute(
            select(FetchRun.status, func.count())
            .where(FetchRun.started_at >= h24)
            .group_by(FetchRun.status)
        ).all()
    )
    ok, err = runs.get("ok", 0), runs.get("error", 0)
    last_fetch = session.scalar(select(func.max(FetchRun.started_at)))

    modules = _module_rows(session, day_start)

    recent_errors = [
        {
            "source_id": sid,
            "name": name,
            "started_at": started.isoformat() if started else None,
            "error": (error or "")[:160],
        }
        for sid, name, started, error in session.execute(
            select(FetchRun.source_id, DataSource.name, FetchRun.started_at, FetchRun.error)
            .join(DataSource, DataSource.id == FetchRun.source_id)
            .where(FetchRun.status == "error", FetchRun.started_at >= h24)
            .order_by(FetchRun.id.desc())
            .limit(10)
        ).all()
    ]

    return {
        "generated_at": now.isoformat(),
        "totals": {
            "content": content_total,
            "today_new": today_new,
            "sources": src_total,
            "sources_enabled": src_enabled,
        },
        "fulltext": {"extracted": ft_ok, "failed": ft_fail, "pending": ft_pending},
        "runs_24h": {
            "ok": ok,
            "error": err,
            "skipped": runs.get("skipped", 0),
            "success_rate": round(ok / (ok + err), 3) if (ok + err) else None,
        },
        "last_fetch_at": last_fetch.isoformat() if last_fetch else None,
        "modules": modules,
        "recent_errors": recent_errors,
    }


def _module_rows(session: Session, day_start: datetime) -> list[dict]:
    totals = dict(
        session.execute(
            select(ContentItem.module, func.count()).group_by(ContentItem.module)
        ).all()
    )
    todays = dict(
        session.execute(
            select(ContentItem.module, func.count())
            .where(ContentItem.fetched_at >= day_start)
            .group_by(ContentItem.module)
        ).all()
    )
    lasts = dict(
        session.execute(
            select(ContentItem.module, func.max(ContentItem.fetched_at)).group_by(
                ContentItem.module
            )
        ).all()
    )
    order = ["news", "events", "calendar", "company", "market", "macro", "opinion", "channel", "person"]
    keys = [m for m in order if m in totals] + [m for m in totals if m not in order]
    return [
        {
            "module": m,
            "total": totals.get(m, 0),
            "today": todays.get(m, 0),
            "last_fetched_at": lasts[m].isoformat() if lasts.get(m) else None,
        }
        for m in keys
    ]


@router.get("/monitor", response_class=HTMLResponse, include_in_schema=False)
def monitor_page() -> str:
    return MONITOR_HTML
