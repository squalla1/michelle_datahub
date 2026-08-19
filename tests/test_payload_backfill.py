"""Source-intrinsic payload backfill from registry categories (feedback P1-3)."""

from __future__ import annotations

import types

import datahub.ingest.runner as runner_mod
from datahub.fetchers.base import FetchResult, RawItem
from datahub.ingest import run_source
from datahub.models import ContentItem, DataSource, FetchRun
from datahub.storage import session_scope


def _src(**kw):
    return types.SimpleNamespace(
        module=kw.get("module"), l1_category=kw.get("l1"), l2_category=kw.get("l2"),
        name=kw.get("name", "n"), url=kw.get("url"),
    )


def test_registry_payload_mappings():
    rp = runner_mod.registry_payload
    assert rp(_src(module="news", l1="1. Regional News", l2="Asia-Pacific")) == {
        "topic": "Asia-Pacific", "region": "Asia-Pacific"}
    assert rp(_src(module="opinion", l1="1. 微博", l2="财经热搜")) == {
        "platform": "微博", "topic": "财经热搜"}
    assert rp(_src(module="person", name="Fei-Fei Li", url="https://x.com/drfeifei")) == {
        "person": "Fei-Fei Li", "platform": "X"}
    assert rp(_src(module="market", l1="2. 债券", l2="美债收益率")) == {
        "asset_class": "债券", "instrument": "美债收益率"}


def test_run_source_merges_registry_payload_fetcher_wins(clean_db, monkeypatch):
    with session_scope() as s:
        src = DataSource(module="opinion", tab="7_关键舆论平台", name="微博财经话题榜",
                         url="http://x", l1_category="1. 微博", l2_category="财经热搜",
                         method="官方RSS", enabled=True)
        s.add(src)
        s.flush()
        sid = src.id

    def fake_fetch(source):
        return FetchResult(items=[
            RawItem(external_id="a", title="t1"),                     # no payload
            RawItem(external_id="b", title="t2", payload={"topic": "覆盖值"}),
        ])

    monkeypatch.setattr(runner_mod, "fetch_source", fake_fetch)
    assert run_source(sid)["new"] == 2

    with session_scope() as s:
        items = {c.external_id: c.payload for c in s.query(ContentItem).all()}
    assert items["a"] == {"platform": "微博", "topic": "财经热搜"}
    # fetcher-provided value wins over the registry-derived one
    assert items["b"]["topic"] == "覆盖值" and items["b"]["platform"] == "微博"


def test_calendar_type_is_the_event_kind_not_the_market():
    """calendar_type was being filled from L2, a region/market ("全球", "美国"),
    so 35 of 39 calendar sources grouped under a value that is not an event
    kind. L1 carries the kind; the region moves to calendar_region."""
    rp = runner_mod.registry_payload
    assert rp(_src(module="calendar", l1="8. 央行日历", l2="日本")) == {
        "calendar_type": "央行", "calendar_region": "日本"}
    assert rp(_src(module="calendar", l1="3. IPO/上市", l2="全球"))["calendar_type"] == "IPO"
    assert rp(_src(module="calendar", l1="9. 国债拍卖日历", l2="中国"))["calendar_type"] == "国债拍卖"
    assert rp(_src(module="calendar", l1="6. 监管/Filing日历", l2="港交所信披"))["calendar_type"] == "监管备案"
    # every mapped value belongs to the published domain
    for l1 in ("1. 财报日历", "2. 分红/拆股", "4. 公司行动", "5. 公司IR事件",
               "7. 经济数据日历", "10. 能源/商品报告日历", "11. 加密事件日历", "12. 科技/AI 活动"):
        assert rp(_src(module="calendar", l1=l1))["calendar_type"] in runner_mod.CALENDAR_TYPES


def test_a_future_published_at_from_a_feed_is_rejected(clean_db, monkeypatch):
    """One Greek news feed stamps articles weeks ahead; such an item pins itself
    to the top of every order=published stream. calendar/events keep theirs."""
    from datetime import timedelta

    from datahub.models import utcnow

    ahead = utcnow() + timedelta(days=25)
    with session_scope() as s:
        for module, tab in (("news", "1_新闻"), ("calendar", "4_日历")):
            s.add(DataSource(module=module, tab=tab, name=f"s-{module}", url="http://x",
                             method="官方RSS", enabled=True))
        s.flush()
        ids = {d.module: d.id for d in s.query(DataSource).all()}

    monkeypatch.setattr(runner_mod, "fetch_source", lambda source: FetchResult(
        items=[RawItem(external_id="a", title="t", published_at=ahead,
                       payload={"event_date": ahead.strftime("%Y-%m-%d %H:%M:%S")})]))
    run_source(ids["news"])
    run_source(ids["calendar"])

    with session_scope() as s:
        by_module = {c.module: c.published_at for c in s.query(ContentItem).all()}
    assert by_module["news"] is None                      # dirty timestamp dropped
    assert by_module["calendar"] is not None              # a scheduled event



def test_a_near_future_published_at_is_clamped_to_the_fetch_time(clean_db, monkeypatch):
    """Bild stamps articles ~1.5h ahead (CEST written as UTC). Dropping the date
    loses more than it fixes at that magnitude, so it is clamped: nothing can
    have been published after the fetch that discovered it."""
    from datetime import timedelta

    from datahub.models import utcnow

    before = utcnow()
    ahead = before + timedelta(hours=2)
    with session_scope() as s:
        s.add(DataSource(module="news", tab="1_新闻", name="bild", url="http://x",
                         method="官方RSS", enabled=True))
        s.flush()
        sid = s.query(DataSource).one().id

    monkeypatch.setattr(runner_mod, "fetch_source", lambda source: FetchResult(
        items=[RawItem(external_id="a", title="t", published_at=ahead)]))
    run_source(sid)

    with session_scope() as s:
        stored = s.query(ContentItem).one().published_at
    assert stored is not None and before <= stored <= utcnow()


def test_a_calendar_item_without_an_event_date_is_not_stored(clean_db, monkeypatch):
    """431-435 stored the central banks' own navigation ("Speeches", "Our
    people") as calendar events. A date filter cannot catch them — their date is
    always today — but an event without an event_date is not an event."""
    with session_scope() as s:
        s.add(DataSource(module="calendar", tab="4_日历", name="boe", url="http://x",
                         l1_category="8. 央行日历", l2_category="英国",
                         method="爬虫", enabled=True))
        s.flush()
        sid = s.query(DataSource).one().id

    monkeypatch.setattr(runner_mod, "fetch_source", lambda source: FetchResult(items=[
        RawItem(external_id="nav", title="Speeches"),
        RawItem(external_id="mpc", title="MPC announcement",
                payload={"event_date": "2026-09-18 11:00:00"}),
    ]))
    summary = run_source(sid)

    assert summary["new"] == 1
    with session_scope() as s:
        rows = s.query(ContentItem).all()
        assert [c.external_id for c in rows] == ["mpc"]
        assert rows[0].payload["calendar_type"] == "央行"
        # the drop is recorded, so a source that produces nothing but navigation
        # is visible in the run log instead of looking like a healthy empty fetch
        run = s.query(FetchRun).one()
        assert "without event_date" in (run.error or "")
