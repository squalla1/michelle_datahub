"""RSS / Atom fetcher — covers the largest method family in the registry:
官方RSS, Google News RSS, NewsAPI/官方RSS, YouTube RSS, 公众号(RSS桥接)."""

from __future__ import annotations

import hashlib
from datetime import datetime

import feedparser
import httpx

from ..config import get_settings
from .base import Fetcher, FetchResult, RawItem


def _entry_id(entry, source_name: str) -> str:
    for key in ("id", "guid", "link"):
        val = entry.get(key)
        if val:
            return str(val)
    basis = f"{source_name}:{entry.get('title', '')}:{entry.get('published', '')}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def _entry_time(entry) -> datetime | None:
    # feedparser's *_parsed structs are already UTC; store naive-UTC (aware
    # values get shifted through the DB session timezone on TIMESTAMP columns).
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6])
    return None


class RssFetcher(Fetcher):
    method_keywords = ("rss", "google news", "newsapi", "youtube", "公众号", "feed", "atom")

    def __init__(self) -> None:
        self._settings = get_settings()

    def _resolve_url(self, source) -> str | None:
        return source.url

    def fetch(self, source) -> FetchResult:
        url = self._resolve_url(source)
        if not url or not url.startswith("http"):
            return FetchResult(status="skipped", note="no fetchable URL")
        try:
            resp = httpx.get(
                url,
                timeout=self._settings.request_timeout,
                headers={"User-Agent": self._settings.user_agent},
                follow_redirects=True,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            return FetchResult(status="error", note=f"http: {exc}")

        feed = feedparser.parse(resp.content)
        items: list[RawItem] = []
        for entry in feed.entries[: self._settings.max_items_per_fetch]:
            items.append(
                RawItem(
                    external_id=_entry_id(entry, source.name),
                    title=entry.get("title"),
                    url=entry.get("link"),
                    summary=entry.get("summary"),
                    published_at=_entry_time(entry),
                    payload={k: v for k, v in (("author", entry.get("author")),) if v},
                )
            )
        note = None if items else "feed parsed but empty"
        return FetchResult(items=items, status="ok", note=note)


class RsshubFetcher(RssFetcher):
    """RSSHub sources (RSSHub·微博 / 雪球 / B站(RSSHub) / RSSHub). If the row
    only carries an RSSHub *path*, prefix the configured RSSHub base URL."""

    method_keywords = ("rsshub",)

    def _resolve_url(self, source) -> str | None:
        url = source.url
        if not url:
            return None
        if url.startswith("http"):
            return url
        base = self._settings.rsshub_base_url.rstrip("/")
        return f"{base}/{url.lstrip('/')}"
