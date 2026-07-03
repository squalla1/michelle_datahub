"""Fulltext enrichment and retention purge."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from datahub.ingest import enrich_fulltext, purge_old_content
from datahub.models import ContentItem, DataSource, FetchRun
from datahub.storage import session_scope


def _seed_source(s) -> int:
    src = DataSource(module="news", tab="1_新闻", name="src", url="http://x", enabled=True)
    s.add(src)
    s.flush()
    return src.id


def test_purge_deletes_only_old_rows(clean_db):
    now = datetime.now(timezone.utc)
    with session_scope() as s:
        sid = _seed_source(s)
        s.add(ContentItem(source_id=sid, module="news", external_id="old",
                          fetched_at=now - timedelta(days=8)))
        s.add(ContentItem(source_id=sid, module="news", external_id="new",
                          fetched_at=now - timedelta(days=1)))
        s.add(FetchRun(source_id=sid, status="ok", started_at=now - timedelta(days=9)))
        s.add(FetchRun(source_id=sid, status="ok", started_at=now))

    result = purge_old_content(days=7)
    assert result["content_deleted"] == 1 and result["runs_deleted"] == 1
    with session_scope() as s:
        remaining = [c.external_id for c in s.query(ContentItem).all()]
        assert remaining == ["new"]


def test_purge_disabled(clean_db):
    assert purge_old_content(days=0)["enabled"] is False


def test_enrich_marks_failures_and_never_retries(clean_db):
    with session_scope() as s:
        sid = _seed_source(s)
        # unreachable URL -> extraction fails -> fulltext becomes "" (attempted)
        s.add(ContentItem(source_id=sid, module="news", external_id="a",
                          url="http://127.0.0.1:1/nope"))
        # no URL -> never selected
        s.add(ContentItem(source_id=sid, module="news", external_id="b", url=None))

    r1 = enrich_fulltext(limit=10)
    assert r1["attempted"] == 1 and r1["failed"] == 1
    with session_scope() as s:
        item = s.query(ContentItem).filter_by(external_id="a").one()
        assert item.fulltext == ""  # failure sentinel

    # second run finds nothing left to attempt
    r2 = enrich_fulltext(limit=10)
    assert r2["attempted"] == 0


def test_scheduler_registers_enrich_and_purge_jobs(clean_db):
    from datahub.scheduler import scheduler_service
    from datahub.scheduler.service import ENRICH_JOB_ID, PURGE_JOB_ID

    counts = scheduler_service.load_jobs()
    assert counts["enrich"] == 1 and counts["purge"] == 1
    assert scheduler_service.scheduler.get_job(ENRICH_JOB_ID) is not None
    assert scheduler_service.scheduler.get_job(PURGE_JOB_ID) is not None
