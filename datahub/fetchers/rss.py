"""RSS / Atom fetcher — covers the largest method family in the registry:
官方RSS, Google News RSS, NewsAPI/官方RSS, YouTube RSS, 公众号(RSS桥接)."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

import feedparser
import httpx

from ..config import get_settings
from .base import Fetcher, FetchResult, RawItem, http_options


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
            resp = httpx.get(url, **http_options(self._settings))
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
        if items:
            return FetchResult(items=items, status="ok")
        # A response that isn't a feed at all (anti-bot page, HTML homepage,
        # Cloudflare challenge) used to be recorded as a healthy empty run —
        # surface it as an error so the monitor shows the source is broken.
        if not getattr(feed, "version", ""):
            return FetchResult(status="error", note=f"not a feed ({url}); blocked page or wrong URL")
        return FetchResult(items=[], status="ok", note="feed parsed but empty")


# Site URL -> RSSHub route. The registry's 链接 column holds the human-facing
# page for most RSSHub rows; RSSHub itself needs its own path, so map them.
# `{}` is filled with the trailing id captured from the site URL.
_RSSHUB_ROUTES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"^https?://s\.weibo\.com/top/summary"), "/weibo/search/hot"),
    (re.compile(r"^https?://(?:www\.|m\.)?weibo\.c(?:om|n)/u/(\d+)"), "/weibo/user/{}"),
    (re.compile(r"^https?://xueqiu\.com/u/(\d+)"), "/xueqiu/user/{}"),
    (re.compile(r"^https?://xueqiu\.com/today"), "/xueqiu/today"),
    (re.compile(r"^https?://xueqiu\.com/hq"), "/xueqiu/hots"),
    (re.compile(r"^https?://space\.bilibili\.com/(\d+)"), "/bilibili/user/video/{}"),
    (re.compile(r"^https?://www\.bilibili\.com/v/popular/all"), "/bilibili/popular/all"),
    (re.compile(r"^https?://www\.zhihu\.com/billboard"), "/zhihu/hotlist"),
    (re.compile(r"^https?://m\.okjike\.com/topics/(\w+)"), "/jike/topic/{}"),
    (re.compile(r"^https?://www\.threads\.net/@([\w.]+)"), "/threads/{}"),
    (re.compile(r"^https?://www\.pbc\.gov\.cn/?$"), "/gov/pbc"),
)

# Rows whose URL is a weibo *vanity* name (weibo.com/leijun) can't be routed:
# RSSHub's /weibo/user/:uid takes a numeric uid only.
_WEIBO_VANITY = re.compile(r"^https?://(?:www\.|m\.)?weibo\.c(?:om|n)/(?!u/)([\w.-]+)/?$")


class RsshubFetcher(RssFetcher):
    """RSSHub sources (RSSHub·微博 / 雪球 / B站(RSSHub) / RSSHub).

    The registry stores three shapes in the 链接 column and all three must end
    up as `<rsshub_base_url>/<route>`:
    - a bare RSSHub path (`/weibo/search/hot`) — prefixed;
    - the `RSSHUB_HOST` placeholder the workbook uses — substituted;
    - the site's own page (`https://s.weibo.com/top/summary`) — mapped via
      `_RSSHUB_ROUTES`, otherwise the row is skipped with a reason instead of
      silently hitting the site itself (which returns an anti-bot page)."""

    method_keywords = ("rsshub",)

    def _route_for(self, source) -> str | None:
        """RSSHub path for this row, or None when it can't be routed."""
        url = (source.url or "").strip()
        # The method column sometimes carries the route: "RSSHub /gov/pbc".
        for token in (source.method or "").split():
            if token.startswith("/"):
                return token
        if not url:
            return None
        if "RSSHUB_HOST" in url:
            return "/" + url.split("RSSHUB_HOST", 1)[1].lstrip("/")
        if not url.startswith("http"):
            return "/" + url.lstrip("/")
        for pattern, route in _RSSHUB_ROUTES:
            m = pattern.match(url)
            if m:
                return route.format(*m.groups()) if m.groups() else route
        return None

    def _resolve_url(self, source) -> str | None:
        route = self._route_for(source)
        if not route:
            return None
        base = self._settings.rsshub_base_url.rstrip("/")
        return f"{base}/{route.lstrip('/')}"

    def fetch(self, source) -> FetchResult:
        if self._route_for(source) is None:
            url = (source.url or "").strip()
            if _WEIBO_VANITY.match(url):
                return FetchResult(
                    status="skipped",
                    note="RSSHub: 微博 route needs the numeric uid "
                         f"(registry has the vanity name '{url}')")
            return FetchResult(status="skipped",
                               note=f"RSSHub: no route mapping for '{url}'")
        return super().fetch(source)
