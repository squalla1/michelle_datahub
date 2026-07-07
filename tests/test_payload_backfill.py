"""Source-intrinsic payload backfill from registry categories (feedback P1-3)."""

from __future__ import annotations

import types

import datahub.ingest.runner as runner_mod
from datahub.fetchers.base import FetchResult, RawItem
from datahub.ingest import run_source
from datahub.models import ContentItem, DataSource
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
