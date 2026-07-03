"""run_all_sources must write a per-run stats report into settings.report_dir."""

from __future__ import annotations

from datahub.config import get_settings
from datahub.ingest import run_all_sources
from datahub.models import DataSource
from datahub.storage import session_scope


def test_refresh_writes_report(clean_db, tmp_path, monkeypatch):
    monkeypatch.setenv("DATAHUB_REPORT_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        with session_scope() as s:
            # URL-less RSS source -> fetcher returns skipped, no network involved
            s.add(DataSource(module="news", tab="1_新闻", name="no-url", url=None,
                             method="官方RSS", enabled=True))
        totals = run_all_sources()
        assert totals["sources"] == 1 and totals["skipped"] == 1

        files = list((tmp_path / "refresh").glob("refresh_*.md"))
        assert len(files) == 1
        assert totals["report"] == str(files[0])
        text = files[0].read_text(encoding="utf-8")
        assert "| news | 1 |" in text
        assert "new items this run: 0" in text
    finally:
        get_settings.cache_clear()


def test_report_disabled_by_empty_dir(clean_db, monkeypatch):
    monkeypatch.setenv("DATAHUB_REPORT_DIR", "")
    get_settings.cache_clear()
    try:
        totals = run_all_sources()
        assert "report" not in totals
    finally:
        get_settings.cache_clear()
