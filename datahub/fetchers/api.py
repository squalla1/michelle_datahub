"""API fetcher — dispatches to per-provider plugins keyed off the `方式` value
(GDELT DOC API, FMP API, AKShare API, ArXiv API, twitterapi.io, FRED, ...).

GDELT and ArXiv are implemented as real, key-free examples. Providers that need
credentials return status="skipped" with a clear note until a key is configured;
add new providers by registering a callable in PROVIDERS."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Callable

import httpx

from ..config import get_settings
from .base import Fetcher, FetchResult, RawItem

ProviderFn = Callable[[object, "ApiFetcher"], FetchResult]


def _hash_id(*parts: str) -> str:
    return hashlib.sha1("|".join(p or "" for p in parts).encode()).hexdigest()


def _gdelt(source, fetcher: "ApiFetcher") -> FetchResult:
    """GDELT 2.0 DOC API — free article search. Uses the source name/category as
    the query when the row carries no explicit query in `account`."""
    query = source.account or source.l2_category or source.name
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": str(min(fetcher.settings.max_items_per_fetch, 75)),
        "sort": "DateDesc",
    }
    try:
        resp = fetcher.client.get(
            "https://api.gdeltproject.org/api/v2/doc/doc", params=params
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        return FetchResult(status="error", note=f"gdelt: {exc}")

    items = []
    for art in data.get("articles", []):
        items.append(
            RawItem(
                external_id=art.get("url") or _hash_id(art.get("title", "")),
                title=art.get("title"),
                url=art.get("url"),
                summary=art.get("domain"),
                published_at=_gdelt_time(art.get("seendate")),
                payload={"language": art.get("language"), "sourcecountry": art.get("sourcecountry")},
            )
        )
    return FetchResult(items=items, status="ok")


def _gdelt_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _arxiv(source, fetcher: "ApiFetcher") -> FetchResult:
    """ArXiv Atom API — free. Delegates parsing to feedparser."""
    import feedparser

    query = source.account or source.l2_category or "cs.AI"
    try:
        resp = fetcher.client.get(
            "http://export.arxiv.org/api/query",
            params={"search_query": f"all:{query}", "max_results": "50", "sortBy": "submittedDate", "sortOrder": "descending"},
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        return FetchResult(status="error", note=f"arxiv: {exc}")
    feed = feedparser.parse(resp.content)
    items = [
        RawItem(
            external_id=e.get("id", _hash_id(e.get("title", ""))),
            title=e.get("title"),
            url=e.get("link"),
            summary=e.get("summary"),
        )
        for e in feed.entries
    ]
    return FetchResult(items=items, status="ok")


def _needs_key(provider: str, key_attr: str) -> ProviderFn:
    def _fn(source, fetcher: "ApiFetcher") -> FetchResult:
        if getattr(fetcher.settings, key_attr, None):
            return FetchResult(status="skipped", note=f"{provider} plugin not implemented yet")
        return FetchResult(status="skipped", note=f"{provider} requires DATAHUB_{key_attr.upper()}")
    return _fn


# method keyword (lowercase substring) -> provider function
PROVIDERS: dict[str, ProviderFn] = {
    "gdelt": _gdelt,
    "arxiv": _arxiv,
    "fmp": _needs_key("FMP", "fmp_api_key"),
    "fred": _needs_key("FRED", "fred_api_key"),
    "twitterapi.io": _needs_key("twitterapi.io", "twitterapi_io_key"),
    "acled": _needs_key("ACLED", "acled_api_key"),
}


class ApiFetcher(Fetcher):
    method_keywords = ("api", "gdelt", "arxiv", "akshare", "twitterapi")

    # Hybrid methods such as "NewsAPI/官方RSS" or "OFAC API/RSS" contain "api"
    # but carry a real feed URL. When we have no provider plugin for them, defer
    # to the RSS fetcher instead of claiming and skipping them here.
    _rss_fallback_keywords = ("rss", "google news", "feed", "atom", "hnrss")

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = httpx.Client(
            timeout=self.settings.request_timeout,
            headers={"User-Agent": self.settings.user_agent},
            follow_redirects=True,
        )

    def supports(self, method: str | None) -> bool:
        if not super().supports(method):
            return False
        if self._provider_for(method) is not None:
            return True
        low = method.lower()
        return not any(k in low for k in self._rss_fallback_keywords)

    def _provider_for(self, method: str | None) -> ProviderFn | None:
        if not method:
            return None
        low = method.lower()
        for key, fn in PROVIDERS.items():
            if key in low:
                return fn
        return None

    def fetch(self, source) -> FetchResult:
        provider = self._provider_for(source.method)
        if provider is None:
            return FetchResult(
                status="skipped",
                note=f"no API provider plugin for method '{source.method}'",
            )
        return provider(source, self)
