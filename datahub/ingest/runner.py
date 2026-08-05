"""Execute a fetch against one source and persist results + an audit run."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..config import get_settings
from ..fetchers import fetch_source
from ..models import ContentItem, DataSource, FetchRun, to_naive_utc, utcnow
from ..storage import session_scope

logger = logging.getLogger("datahub.runner")

_NUM_PREFIX = None  # compiled lazily


def _strip_num(text: str | None) -> str | None:
    """'1. 微博' -> '微博' (registry L1 categories carry a numeric prefix)."""
    global _NUM_PREFIX
    if not text:
        return None
    if _NUM_PREFIX is None:
        import re

        _NUM_PREFIX = re.compile(r"^\s*\d+[\.、]\s*")
    return _NUM_PREFIX.sub("", text).strip() or None


def registry_payload(source: DataSource) -> dict:
    """Source-intrinsic payload fields derived from the registry row itself
    (its L1/L2 categories, name, url). Fetcher-provided values always win —
    callers must merge with `{**registry_payload(src), **item.payload}`."""
    l1, l2 = _strip_num(source.l1_category), (source.l2_category or "").strip() or None
    m = source.module
    out: dict[str, str] = {}
    if m == "news":
        if l2:
            out["topic"] = l2
        if l1 and "regional" in l1.lower() and l2:
            out["region"] = l2
    elif m == "events":
        if l2:
            out["event_type"] = l2
    elif m == "calendar":
        if l2:
            out["calendar_type"] = l2
    elif m == "company":
        if l2:
            out["data_type"] = l2
    elif m == "market":
        if l1:
            out["asset_class"] = l1
        if l2:
            out["instrument"] = l2
    elif m == "macro":
        if l2:
            out["indicator"] = l2
    elif m == "opinion":
        if l1:
            out["platform"] = l1
        if l2:
            out["topic"] = l2
    elif m == "channel":
        if l1:
            out["medium"] = l1
        if l2:
            out["topic"] = l2
    elif m == "person":
        out["person"] = source.name
        url = source.url or ""
        for dom, plat in (("x.com", "X"), ("twitter.com", "X"), ("weibo", "微博"),
                          ("xueqiu", "雪球"), ("substack", "Substack"), ("youtube", "YouTube")):
            if dom in url:
                out["platform"] = plat
                break
        else:
            if l1:
                out["platform"] = l1
    return out


def run_source(source_id: int) -> dict:
    """Fetch a single source, dedup-store its items, and record a FetchRun.

    Returns a summary dict suitable for API/CLI output."""
    with session_scope() as session:
        source = session.get(DataSource, source_id)
        if source is None:
            return {"error": "source not found", "source_id": source_id}

        run = FetchRun(source_id=source.id, status="running")
        session.add(run)
        session.flush()

        result = fetch_source(source)
        new_count = 0

        if result.status == "ok":
            existing_ids = set(
                session.scalars(
                    select(ContentItem.external_id).where(
                        ContentItem.source_id == source.id
                    )
                )
            )
            base_payload = registry_payload(source)
            for item in result.items:
                if item.external_id in existing_ids:
                    continue
                session.add(
                    ContentItem(
                        source_id=source.id,
                        module=source.module,
                        external_id=item.external_id,
                        title=item.title,
                        url=item.url,
                        summary=item.summary,
                        image_url=item.image_url,
                        published_at=to_naive_utc(item.published_at),
                        # source-intrinsic fields from the registry; fetcher wins
                        payload={**base_payload, **(item.payload or {})},
                    )
                )
                existing_ids.add(item.external_id)
                new_count += 1

        run.status = result.status
        run.item_count = len(result.items)
        run.new_count = new_count
        # Keep the note even on a successful run: "feed parsed but empty" is the
        # only trace left when a source silently stops producing items.
        run.error = result.note
        run.finished_at = utcnow()

        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            return {"source_id": source_id, "status": "error", "error": "integrity"}

        return {
            "source_id": source.id,
            "name": source.name,
            "module": source.module,
            "status": run.status,
            "fetched": run.item_count,
            "new": run.new_count,
            "note": result.note,
        }


def run_all_sources(module: str | None = None, only_enabled: bool = True) -> dict:
    """Fetch every (optionally module-filtered, enabled) source once.

    This is the global-refresh entrypoint: it loops `run_source` over each
    matching source id, so the same (source_id, external_id) dedup applies and
    repeated refreshes only persist genuinely new items. Returns an aggregate
    summary and writes a per-run stats report to `settings.report_dir`.
    Individual source failures are logged and never abort the sweep."""
    started_at = utcnow()
    with session_scope() as session:
        stmt = select(DataSource.id)
        if only_enabled:
            stmt = stmt.where(DataSource.enabled.is_(True))
        if module:
            stmt = stmt.where(DataSource.module == module)
        ids = list(session.scalars(stmt))

    totals = {"sources": len(ids), "ok": 0, "error": 0, "skipped": 0, "new_items": 0}
    per_module: dict[str, dict] = {}
    for sid in ids:
        try:
            summary = run_source(sid)
        except Exception:  # a single source must not abort the whole refresh
            logger.exception("refresh: source=%s raised", sid)
            totals["error"] += 1
            continue
        status = summary.get("status")
        if status in totals:
            totals[status] += 1
        totals["new_items"] += summary.get("new", 0) or 0
        mod = summary.get("module") or "?"
        m = per_module.setdefault(
            mod, {"sources": 0, "ok": 0, "error": 0, "skipped": 0, "new_items": 0}
        )
        m["sources"] += 1
        if status in m:
            m[status] += 1
        m["new_items"] += summary.get("new", 0) or 0

    finished_at = utcnow()
    report = _write_refresh_report(totals, per_module, started_at, finished_at)
    if report:
        totals["report"] = str(report)
    logger.info("refresh complete: %s", totals)
    return totals


def _write_refresh_report(
    totals: dict, per_module: dict[str, dict], started_at: datetime, finished_at: datetime
) -> Path | None:
    """Write one markdown stats file per refresh run into settings.report_dir.

    Reporting must never break the refresh itself: any failure is logged and
    swallowed."""
    settings = get_settings()
    if not settings.report_dir:
        return None
    try:
        with session_scope() as session:
            db_counts = dict(
                session.execute(
                    select(ContentItem.module, func.count()).group_by(ContentItem.module)
                ).all()
            )
            db_total = session.scalar(select(func.count()).select_from(ContentItem))

        duration = int((finished_at - started_at).total_seconds())
        stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
        lines = [
            f"# Refresh Report — {started_at.strftime('%Y-%m-%d %H:%M:%S')} UTC",
            "",
            f"- window: {started_at.isoformat()} → {finished_at.isoformat()} "
            f"({duration // 60}m{duration % 60:02d}s)",
            f"- sources: {totals['sources']} | ok {totals['ok']} | "
            f"error {totals['error']} | skipped {totals['skipped']}",
            f"- new items this run: {totals['new_items']}",
            f"- content_item total in DB: {db_total}",
            "",
            "| module | sources | ok | error | skipped | new items | total in DB |",
            "|---|---|---|---|---|---|---|",
        ]
        for mod in sorted(per_module, key=lambda k: -per_module[k]["new_items"]):
            m = per_module[mod]
            lines.append(
                f"| {mod} | {m['sources']} | {m['ok']} | {m['error']} | "
                f"{m['skipped']} | {m['new_items']} | {db_counts.get(mod, 0)} |"
            )
        out_dir = Path(settings.report_dir) / "refresh"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"refresh_{stamp}.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
    except Exception:
        logger.exception("failed to write refresh report")
        return None
