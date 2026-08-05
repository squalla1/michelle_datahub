"""Best-effort HTML scraper for 爬虫 / 官方(爬取) sources.

Generic implementation: fetches the page and extracts anchor links as items.
Site-specific extraction (巨潮 / HKEX / Nasdaq ...) should subclass this or be
registered per-domain; the generic path keeps such sources observable until a
tailored parser is added."""

from __future__ import annotations

import hashlib
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from ..config import get_settings
from .base import Fetcher, FetchResult, RawItem, http_options


class ScraperFetcher(Fetcher):
    method_keywords = ("爬虫", "爬取", "scrape", "crawl")

    def __init__(self) -> None:
        self._settings = get_settings()

    def fetch(self, source) -> FetchResult:
        if not source.url or not source.url.startswith("http"):
            return FetchResult(status="skipped", note="no fetchable URL")
        try:
            resp = httpx.get(source.url, **http_options(self._settings))
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            return FetchResult(status="error", note=f"http: {exc}")

        soup = BeautifulSoup(resp.text, "html.parser")
        seen: set[str] = set()
        items: list[RawItem] = []
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            if not text or len(text) < 8:
                continue
            href = urljoin(source.url, a["href"])
            if href in seen:
                continue
            seen.add(href)
            items.append(
                RawItem(
                    external_id=hashlib.sha1(href.encode()).hexdigest(),
                    title=text,
                    url=href,
                )
            )
            if len(items) >= self._settings.max_items_per_fetch:
                break
        return FetchResult(items=items, status="ok", note="generic link extraction")
