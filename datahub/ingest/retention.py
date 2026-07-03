"""Retention purge: keep only `retention_days` of data.

Deletes content_item rows by fetched_at and fetch_run rows by started_at.
Caveat: deleting content also deletes its dedup keys — if a purged item still
appears in a source's feed it will be re-ingested as new. Feeds rarely carry
week-old entries, so with the default 7 days this is negligible.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from ..config import get_settings
from ..models import ContentItem, FetchRun
from ..storage import session_scope

logger = logging.getLogger("datahub.retention")


def purge_old_content(days: int | None = None) -> dict:
    """Delete content and run-audit rows older than the retention window.
    Returns deletion counts; days<=0 (or retention disabled) is a no-op."""
    settings = get_settings()
    days = settings.retention_days if days is None else days
    if not days or days <= 0:
        return {"enabled": False, "content_deleted": 0, "runs_deleted": 0}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with session_scope() as session:
        content_deleted = session.execute(
            delete(ContentItem).where(ContentItem.fetched_at < cutoff)
        ).rowcount
        runs_deleted = session.execute(
            delete(FetchRun).where(FetchRun.started_at < cutoff)
        ).rowcount

    summary = {
        "cutoff": cutoff.isoformat(),
        "content_deleted": content_deleted,
        "runs_deleted": runs_deleted,
    }
    logger.info("retention purge: %s", summary)
    return summary
