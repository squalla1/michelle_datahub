"""Full-text enrichment: fetch each stored item's URL and extract the article
body into content_item.fulltext.

Convention: fulltext is NULL until attempted; "" marks an attempt that failed
(paywall, anti-bot, non-article page, dead link) so the item is never retried.
Runs as a scheduled job (every fulltext_interval_minutes) and via
`datahub enrich`.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

import httpx
from sqlalchemy import select

from ..config import get_settings
from ..models import ContentItem
from ..storage import session_scope

logger = logging.getLogger("datahub.enrich")


def _extract(url: str, client: httpx.Client, max_chars: int) -> str:
    """Fetch a URL and extract the readable article text. Returns "" on any
    failure — enrichment must never raise."""
    import trafilatura

    try:
        resp = client.get(url)
        resp.raise_for_status()
        text = trafilatura.extract(resp.text, include_comments=False, favor_precision=True)
    except Exception:
        return ""
    if not text:
        return ""
    return text[:max_chars]


def enrich_fulltext(limit: int | None = None, module: str | None = None) -> dict:
    """Enrich up to `limit` items whose fulltext is still NULL (newest first).

    Network I/O runs concurrently; DB writes happen in one batch afterwards so
    no transaction stays open across slow fetches."""
    settings = get_settings()
    if not settings.fulltext_enabled:
        return {"enabled": False, "attempted": 0, "extracted": 0, "failed": 0}
    limit = limit or settings.fulltext_batch_size

    with session_scope() as session:
        stmt = (
            select(ContentItem.id, ContentItem.url)
            .where(ContentItem.fulltext.is_(None), ContentItem.url.isnot(None))
            .order_by(ContentItem.id.desc())
            .limit(limit)
        )
        if module:
            stmt = stmt.where(ContentItem.module == module)
        targets = [(i, u) for i, u in session.execute(stmt) if u and u.startswith("http")]

    if not targets:
        return {"attempted": 0, "extracted": 0, "failed": 0}

    client = httpx.Client(
        timeout=settings.request_timeout,
        headers={"User-Agent": settings.user_agent},
        follow_redirects=True,
    )
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            texts = list(
                pool.map(lambda t: _extract(t[1], client, settings.fulltext_max_chars), targets)
            )
    finally:
        client.close()

    extracted = 0
    with session_scope() as session:
        for (item_id, _), text in zip(targets, texts):
            item = session.get(ContentItem, item_id)
            if item is not None and item.fulltext is None:
                item.fulltext = text
                if text:
                    extracted += 1

    summary = {"attempted": len(targets), "extracted": extracted, "failed": len(targets) - extracted}
    logger.info("fulltext enrich: %s", summary)
    return summary
