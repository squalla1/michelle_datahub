"""Resolve a source's `方式` (method) value to the right fetcher.

Order matters: more specific fetchers (RSSHub, Email) are tried before the
generic RSS fetcher so that e.g. "RSSHub·微博" routes to RsshubFetcher."""

from __future__ import annotations

from functools import lru_cache

from .api import ApiFetcher
from .base import Fetcher, FetchResult
from .email_sub import EmailSubscriptionFetcher
from .rss import RssFetcher, RsshubFetcher
from .scraper import ScraperFetcher


@lru_cache
def _fetchers() -> tuple[Fetcher, ...]:
    return (
        RsshubFetcher(),
        EmailSubscriptionFetcher(),
        ApiFetcher(),
        ScraperFetcher(),
        RssFetcher(),  # broad fallback for any *RSS* method
    )


def resolve_fetcher(method: str | None) -> Fetcher | None:
    for fetcher in _fetchers():
        if fetcher.supports(method):
            return fetcher
    return None


def fetch_source(source) -> FetchResult:
    fetcher = resolve_fetcher(source.method)
    if fetcher is None:
        return FetchResult(status="skipped", note=f"no fetcher for method '{source.method}'")
    return fetcher.fetch(source)
