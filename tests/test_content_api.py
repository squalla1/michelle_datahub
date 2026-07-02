"""API tests for the per-type / by-date content endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from datahub.api.app import create_app
from datahub.models import ContentItem, DataSource
from datahub.storage import session_scope


def _seed():
    today = datetime.now(timezone.utc)
    yesterday = today - timedelta(days=1)
    with session_scope() as s:
        src = DataSource(module="news", tab="1_新闻", name="src", url="http://x", enabled=True)
        s.add(src)
        s.flush()
        # 3 items today, 1 yesterday, plus one in another module today
        for i in range(3):
            s.add(ContentItem(source_id=src.id, module="news", external_id=f"t{i}",
                              title=f"today {i}", published_at=today - timedelta(minutes=i)))
        s.add(ContentItem(source_id=src.id, module="news", external_id="y0",
                          title="yesterday", published_at=yesterday))
        s.add(ContentItem(source_id=src.id, module="events", external_id="e0",
                          title="event today", published_at=today))
    return today.date()


@pytest.fixture
def client(clean_db):
    _seed()
    return TestClient(create_app())


def test_module_endpoint_defaults_to_today(client):
    r = client.get("/api/v1/content/news")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 3  # yesterday's item excluded by default (today only)
    assert all(it["module"] == "news" for it in items)


def test_module_endpoint_limit_returns_latest_n(client):
    r = client.get("/api/v1/content/news", params={"limit": 1})
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["title"] == "today 0"  # newest published first


def test_module_endpoint_explicit_past_date(client):
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    r = client.get("/api/v1/content/news", params={"date": yesterday})
    assert [it["title"] for it in r.json()] == ["yesterday"]


def test_unknown_module_is_404(client):
    assert client.get("/api/v1/content/not-a-module").status_code == 404


def test_module_isolation(client):
    assert len(client.get("/api/v1/content/events").json()) == 1
