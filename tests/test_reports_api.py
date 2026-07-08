"""Refresh-report listing/viewing/downloading endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from datahub.api.app import create_app
from datahub.config import get_settings

REPORT = "# Refresh Report — test\n\n- sources: 1\n\n| module | ok |\n|---|---|\n| news | 1 |\n"


@pytest.fixture
def client(clean_db, tmp_path, monkeypatch):
    (tmp_path / "refresh").mkdir()
    (tmp_path / "refresh" / "refresh_20260708T020000Z.md").write_text(REPORT, encoding="utf-8")
    monkeypatch.setenv("DATAHUB_REPORT_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield TestClient(create_app())
    get_settings.cache_clear()


def test_list_reports(client):
    d = client.get("/api/v1/reports").json()
    assert d["count"] == 1
    assert d["reports"][0]["name"] == "refresh_20260708T020000Z.md"
    assert d["reports"][0]["size"] > 0


def test_view_and_download(client):
    r = client.get("/api/v1/reports/refresh_20260708T020000Z.md")
    assert r.status_code == 200 and "Refresh Report" in r.text
    assert "content-disposition" not in r.headers
    r = client.get("/api/v1/reports/refresh_20260708T020000Z.md", params={"download": 1})
    assert r.headers["content-disposition"].startswith("attachment")


def test_path_traversal_and_unknown_rejected(client):
    assert client.get("/api/v1/reports/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert client.get("/api/v1/reports/refresh_00000000T000000Z.md").status_code == 404
    assert client.get("/api/v1/reports/other.md").status_code == 404


def test_reports_page(client):
    r = client.get("/reports")
    assert r.status_code == 200 and "刷新报告" in r.text
