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


_IMG_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")


def _entry_media(entry) -> tuple[str | None, dict]:
    """Pull media attachments out of a feed entry.

    Returns (image_url, payload_extras) where payload_extras may carry
    audio_url/audio_mime/audio_duration (podcast enclosures) and
    video_url/video_id (video enclosures, YouTube feeds)."""
    image = audio = video = audio_mime = None

    for thumb in entry.get("media_thumbnail") or []:
        image = image or thumb.get("url")
    for media in entry.get("media_content") or []:
        url = media.get("url")
        if not url:
            continue
        kind = (media.get("medium") or media.get("type") or "").lower()
        if kind.startswith("image") and not image:
            image = url
        elif kind.startswith("audio") and not audio:
            audio, audio_mime = url, media.get("type")
        elif kind.startswith("video") and not video:
            video = url
    for enc in entry.get("enclosures") or []:
        url = enc.get("href") or enc.get("url")
        if not url:
            continue
        mime = (enc.get("type") or "").lower()
        if not image and (mime.startswith("image") or url.lower().endswith(_IMG_EXTS)):
            image = url
        elif mime.startswith("audio") and not audio:
            audio, audio_mime = url, enc.get("type")
        elif mime.startswith("video") and not video:
            video = url
    if not video and entry.get("yt_videoid"):
        video = entry.get("link")

    extras: dict = {}
    if audio:
        extras["audio_url"] = audio
        if audio_mime:
            extras["audio_mime"] = audio_mime
        if entry.get("itunes_duration"):
            extras["audio_duration"] = str(entry["itunes_duration"])
    if video:
        extras["video_url"] = video
        if entry.get("yt_videoid"):
            extras["video_id"] = entry["yt_videoid"]
    return image, extras


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
            image_url, media = _entry_media(entry)
            payload = {k: v for k, v in (("author", entry.get("author")),) if v}
            payload.update(media)
            items.append(
                RawItem(
                    external_id=_entry_id(entry, source.name),
                    title=entry.get("title"),
                    url=entry.get("link"),
                    summary=entry.get("summary"),
                    image_url=image_url,
                    published_at=_entry_time(entry),
                    payload=payload,
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
