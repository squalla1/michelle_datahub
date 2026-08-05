"""RSSHub route resolution (no network).

The registry stores three URL shapes for RSSHub rows — a bare path, the
`RSSHUB_HOST` placeholder, and the site's own page — and all three must resolve
to the configured RSSHub instance. Rows that can't be routed must be reported,
not silently fetched from the site itself (which returns an anti-bot page and
used to be recorded as a healthy empty run)."""

from __future__ import annotations

from types import SimpleNamespace

from datahub.fetchers.rss import RsshubFetcher


def _src(url, method="RSSHub", name="x"):
    return SimpleNamespace(url=url, method=method, name=name, module="opinion",
                           l1_category=None, l2_category=None, account=None)


def test_bare_path_and_placeholder_are_prefixed():
    f = RsshubFetcher()
    base = f._settings.rsshub_base_url.rstrip("/")
    assert f._resolve_url(_src("/weibo/search/hot")) == f"{base}/weibo/search/hot"
    assert f._resolve_url(_src("https://RSSHUB_HOST/36kr/newsflashes")) == f"{base}/36kr/newsflashes"


def test_site_urls_map_to_routes():
    f = RsshubFetcher()
    base = f._settings.rsshub_base_url.rstrip("/")
    cases = {
        "https://s.weibo.com/top/summary?cate=realtimehot": "/weibo/search/hot",
        "https://weibo.com/u/2455476364": "/weibo/user/2455476364",
        "https://m.weibo.cn/u/5884573948": "/weibo/user/5884573948",
        "https://xueqiu.com/u/1247347556": "/xueqiu/user/1247347556",
        "https://xueqiu.com/today": "/xueqiu/today",
        "https://space.bilibili.com/662660667": "/bilibili/user/video/662660667",
        "https://www.bilibili.com/v/popular/all": "/bilibili/popular/all",
        "https://www.zhihu.com/billboard": "/zhihu/hotlist",
        "https://m.okjike.com/topics/63579abb6724cc583b9bba9a": "/jike/topic/63579abb6724cc583b9bba9a",
        "https://www.threads.net/@zuck": "/threads/zuck",
    }
    for url, route in cases.items():
        assert f._resolve_url(_src(url)) == f"{base}{route}", url


def test_route_can_come_from_the_method_column():
    f = RsshubFetcher()
    base = f._settings.rsshub_base_url.rstrip("/")
    assert f._resolve_url(_src("http://www.pbc.gov.cn/", method="RSSHub /gov/pbc")) == \
        f"{base}/gov/pbc"


def test_unroutable_rows_are_skipped_with_a_reason():
    f = RsshubFetcher()
    res = f.fetch(_src("https://weibo.com/leijun", method="RSSHub·微博"))
    assert res.status == "skipped" and "uid" in res.note
    res = f.fetch(_src("https://example.com/whatever"))
    assert res.status == "skipped" and "no route mapping" in res.note
