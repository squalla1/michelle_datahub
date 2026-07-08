"""Data-monitoring endpoints: aggregate stats JSON + self-contained HTML pages.

GET /monitor                 — dashboard page (inline CSS/JS, fetches /api/v1/stats)
GET /api/v1/stats            — the aggregates powering it
GET /reports                 — refresh-report browser page
GET /api/v1/reports          — list per-refresh stats reports
GET /api/v1/reports/{name}   — view (?download=1 to download) one report
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...models import ContentItem, DataSource, FetchRun
from ..deps import get_session
from ..monitor_page import MONITOR_HTML, REPORTS_HTML

router = APIRouter(tags=["monitor"])

# strict allow-list of report filenames — no path separators can ever match
_REPORT_NAME = re.compile(r"^refresh_\d{8}T\d{6}Z\.md$")


def _report_dir() -> Path:
    return Path(get_settings().report_dir) / "refresh"


@router.get("/api/v1/stats")
def stats(session: Session = Depends(get_session)) -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # columns are naive-UTC
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


@router.get("/api/v1/reports")
def list_reports() -> dict:
    """List per-refresh stats reports, newest first."""
    d = _report_dir()
    reports = []
    if d.is_dir():
        for p in sorted(d.glob("refresh_*.md"), reverse=True):
            if not _REPORT_NAME.match(p.name):
                continue
            st = p.stat()
            reports.append(
                {
                    "name": p.name,
                    "size": st.st_size,
                    "modified_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
                    .replace(tzinfo=None)
                    .isoformat(),
                }
            )
    return {"count": len(reports), "reports": reports}


@router.get("/api/v1/reports/{name}")
def get_report(name: str, download: bool = False) -> PlainTextResponse:
    """Return one report as markdown text; `?download=1` forces a download."""
    if not _REPORT_NAME.match(name):
        raise HTTPException(404, "report not found")
    path = _report_dir() / name
    if not path.is_file():
        raise HTTPException(404, "report not found")
    headers = {"Content-Disposition": f'attachment; filename="{name}"'} if download else {}
    return PlainTextResponse(
        path.read_text(encoding="utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers=headers,
    )


@router.get("/monitor", response_class=HTMLResponse, include_in_schema=False)
def monitor_page() -> str:
    return MONITOR_HTML


@router.get("/reports", response_class=HTMLResponse, include_in_schema=False)
def reports_page() -> str:
    return REPORTS_HTML
