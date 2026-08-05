"""Full-text enrichment: fetch each stored item's URL and extract the article
body into content_item.fulltext.

Also fixes two source-quality gaps at the same pass (feedback 2026-07-06):
- Google News links (news.google.com/rss/articles/...) are base64-encoded
  redirects that no extractor can read. They are decoded to the real article
  URL first; the canonical URL is stored in payload["canonical_url"] so the
  engine can dedup/trace by origin.
- If the item has no published_at, the article page's metadata date is used
  to backfill it.

Convention: fulltext is NULL until attempted; "" marks a *permanent* failure
(paywall, anti-bot, non-article page, dead link) and is never retried. A failed
Google News *decode* is treated as transient (kept NULL, retried next run).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy import select

from ..config import get_settings
from ..fetchers.base import http_options
from ..models import ContentItem
from ..storage import session_scope

logger = logging.getLogger("datahub.enrich")

_GN_HOST = "news.google.com"


@dataclass
class _Extract:
    text: str | None          # None = transient failure (retry later), "" = permanent
    canonical: str | None = None
    published: datetime | None = None
    image: str | None = None  # page og:image, for items whose feed had no media


def _decode_gnews(url: str) -> str | None:
    """Resolve a Google News redirect link to the real article URL."""
    try:
        from googlenewsdecoder import gnewsdecoder

        res = gnewsdecoder(url)
        if res.get("status") and res.get("decoded_url"):
            return res["decoded_url"]
    except Exception:
        pass
    return None


def _page_meta(html: str) -> tuple[datetime | None, str | None]:
    """(publication date, og:image) from the article page's metadata."""
    date = image = None
    try:
        import trafilatura

        from ..models import to_naive_utc

        meta = trafilatura.extract_metadata(html)
        if meta:
            image = getattr(meta, "image", None) or None
            if meta.date:
                date = to_naive_utc(datetime.fromisoformat(meta.date))
    except Exception:
        pass
    return date, image


def _extract(url: str, client: httpx.Client, max_chars: int) -> _Extract:
    """Fetch a URL and extract the readable article text + metadata.
    Never raises."""
    import trafilatura

    canonical = None
    if _GN_HOST in url:
        real = _decode_gnews(url)
        if not real:
            return _Extract(text=None)  # transient: retry next run
        canonical, url = real, real

    try:
        resp = client.get(url)
        resp.raise_for_status()
        html = resp.text
        text = trafilatura.extract(html, include_comments=False, favor_precision=True)
    except Exception:
        return _Extract(text="", canonical=canonical)
    published, image = _page_meta(html)
    return _Extract(
        text=(text or "")[:max_chars],
        canonical=canonical,
        published=published,
        image=image,
    )


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
        **http_options(settings, user_agent=settings.enrich_user_agent)
    )
    try:
        with ThreadPoolExecutor(max_workers=settings.fulltext_workers) as pool:
            outs = list(
                pool.map(lambda t: _extract(t[1], client, settings.fulltext_max_chars), targets)
            )
    finally:
        client.close()

    extracted = failed = deferred = resolved = dated = imaged = 0
    with session_scope() as session:
        for (item_id, _), out in zip(targets, outs):
            if out.text is None:
                deferred += 1  # transient (e.g. GN decode hiccup): stays NULL
                continue
            item = session.get(ContentItem, item_id)
            if item is None or item.fulltext is not None:
                continue
            item.fulltext = out.text
            if out.text:
                extracted += 1
            else:
                failed += 1
            if out.canonical:
                item.payload = {**(item.payload or {}), "canonical_url": out.canonical}
                resolved += 1
            if out.published is not None and item.published_at is None:
                item.published_at = out.published
                dated += 1
            if out.image and item.image_url is None:
                item.image_url = out.image
                imaged += 1

    summary = {
        "attempted": len(targets), "extracted": extracted, "failed": failed,
        "deferred": deferred, "canonical_resolved": resolved, "dates_backfilled": dated,
        "images_backfilled": imaged,
    }
    logger.info("fulltext enrich: %s", summary)
    return summary
