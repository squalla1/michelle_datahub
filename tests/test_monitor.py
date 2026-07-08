"""Monitoring page + stats endpoint."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from datahub.api.app import create_app
from datahub.models import ContentItem, DataSource, FetchRun
from datahub.storage import session_scope


@pytest.fixture
def client(clean_db):
    now = datetime.now(timezone.utc)
    with session_scope() as s:
        src = DataSource(module="news", tab="1_新闻", name="src", url="http://x", enabled=True)
        s.add(src)
        s.flush()
        s.add(ContentItem(source_id=src.id, module="news", external_id="a",
                          fulltext="正文", fetched_at=now))
        s.add(ContentItem(source_id=src.id, module="news", external_id="b",
                          fulltext="", fetched_at=now))
        s.add(ContentItem(source_id=src.id, module="events", external_id="c",
                          fetched_at=now - timedelta(days=2)))
        s.add(FetchRun(source_id=src.id, status="ok", started_at=now))
        s.add(FetchRun(source_id=src.id, status="error", error="boom", started_at=now))
    return TestClient(create_app())


def test_stats_shape_and_counts(client):
    d = client.get("/api/v1/stats").json()
    assert d["totals"]["content"] == 3 and d["totals"]["today_new"] == 2
    assert d["fulltext"] == {"extracted": 1, "failed": 1, "pending": 1}
    assert d["runs_24h"]["ok"] == 1 and d["runs_24h"]["error"] == 1
    assert d["runs_24h"]["success_rate"] == 0.5
    mods = {m["module"]: m for m in d["modules"]}
    assert mods["news"]["today"] == 2 and mods["events"]["total"] == 1
    assert d["recent_errors"][0]["error"] == "boom"


def test_monitor_page_serves_html(client):
    r = client.get("/monitor")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "数据监控" in r.text and "api/v1/stats" in r.text
