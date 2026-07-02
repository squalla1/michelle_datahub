"""Execute a fetch against one source and persist results + an audit run."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..fetchers import fetch_source
from ..models import ContentItem, DataSource, FetchRun
from ..storage import session_scope

logger = logging.getLogger("datahub.runner")


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
                        published_at=item.published_at,
                        payload=item.payload,
                    )
                )
                existing_ids.add(item.external_id)
                new_count += 1

        run.status = result.status
        run.item_count = len(result.items)
        run.new_count = new_count
        run.error = result.note if result.status in {"error", "skipped"} else None
        run.finished_at = datetime.now(timezone.utc)

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
    summary. Individual source failures are logged and never abort the sweep."""
    with session_scope() as session:
        stmt = select(DataSource.id)
        if only_enabled:
            stmt = stmt.where(DataSource.enabled.is_(True))
        if module:
            stmt = stmt.where(DataSource.module == module)
        ids = list(session.scalars(stmt))

    totals = {"sources": len(ids), "ok": 0, "error": 0, "skipped": 0, "new_items": 0}
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
    logger.info("refresh complete: %s", totals)
    return totals
