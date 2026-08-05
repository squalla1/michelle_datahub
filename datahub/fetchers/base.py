"""Fetcher abstraction. A fetcher knows how to pull items from sources of a
given `方式` (method) family and normalize them into RawItem objects."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


def http_options(settings, *, user_agent: str | None = None) -> dict:
    """Shared httpx kwargs for every outbound fetch: UA, timeout, redirects and
    the optional egress proxy (`DATAHUB_HTTP_PROXY`). Accepted by both
    `httpx.get(...)` and `httpx.Client(...)`."""
    opts: dict = {
        "timeout": settings.request_timeout,
        "headers": {"User-Agent": user_agent or settings.user_agent},
        "follow_redirects": True,
    }
    if getattr(settings, "http_proxy", None):
        opts["proxy"] = settings.http_proxy
    return opts


@dataclass
class RawItem:
    external_id: str
    title: str | None = None
    url: str | None = None
    summary: str | None = None
    image_url: str | None = None
    published_at: datetime | None = None
    payload: dict = field(default_factory=dict)


@dataclass
class FetchResult:
    items: list[RawItem] = field(default_factory=list)
    status: str = "ok"          # ok / skipped / error
    note: str | None = None


class Fetcher(ABC):
    """Base class. `method_keywords` are case-insensitive substrings matched
    against a source's `方式` value to route it to this fetcher."""

    method_keywords: tuple[str, ...] = ()

    def supports(self, method: str | None) -> bool:
        if not method:
            return False
        low = method.lower()
        return any(k.lower() in low for k in self.method_keywords)

    @abstractmethod
    def fetch(self, source) -> FetchResult:
        """`source` is a datahub.models.DataSource (or any object exposing the
        same attributes). Implementations must not raise for expected failures —
        return FetchResult(status="error", note=...) instead."""
        raise NotImplementedError
