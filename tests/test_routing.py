"""Regression tests for `方式` -> fetcher routing (fetchers/registry.py)."""

from __future__ import annotations

import pytest

from datahub.fetchers.api import ApiFetcher
from datahub.fetchers.registry import resolve_fetcher
from datahub.fetchers.rss import RssFetcher


@pytest.mark.parametrize(
    "method",
    [
        "NewsAPI/官方RSS",
        "NewsAPI/Google News RSS",
        "GitHub API / hnrss",
        "OFAC API/RSS",
        "SEC EDGAR API/RSS",
    ],
)
def test_hybrid_api_rss_methods_route_to_rss(method):
    """Methods that contain "api" but carry a feed URL must reach the RSS
    fetcher, not be claimed-and-skipped by ApiFetcher."""
    assert type(resolve_fetcher(method)) is RssFetcher


@pytest.mark.parametrize(
    "method",
    ["FMP API", "AKShare API", "US Census API", "GDELT DOC API", "ArXiv API"],
)
def test_genuine_api_methods_stay_on_api_fetcher(method):
    assert type(resolve_fetcher(method)) is ApiFetcher
