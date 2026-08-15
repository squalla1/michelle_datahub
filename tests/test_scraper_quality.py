"""Generic scraper: what counts as content and what is site skeleton.

The naive anchor sweep filled company/calendar sources with the sites' own
chrome — ICP filing numbers, "投资者_1735799206356" profile links, service
menus, and (when the origin answered with a stock server page) nginx's own
links. These tests pin the filtering down; no network is involved.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from datahub.fetchers.scraper import ScraperFetcher, _cninfo_published


class _Resp:
    def __init__(self, text, url):
        self.text, self.url = text, url

    def raise_for_status(self):
        return None


def _fetch(monkeypatch, html, url="https://sns.example.com/list"):
    monkeypatch.setattr("datahub.fetchers.scraper.httpx.get",
                        lambda *a, **k: _Resp(html, url))
    return ScraperFetcher().fetch(SimpleNamespace(url=url, method="爬虫", name="x",
                                                  module="company"))


def test_chrome_regions_and_offsite_links_are_dropped(monkeypatch):
    html = """
    <html><body>
      <nav><a href="/about-the-exchange">上证所信息网络有限公司</a></nav>
      <div class="main">
        <a href="/notice/12345">某某股份有限公司2026年半年度报告摘要</a>
      </div>
      <footer>
        <a href="https://beian.miit.gov.cn/">沪B2-20050241-2</a>
        <a href="http://edu.sse.com.cn">上证所投资者教育网站</a>
      </footer>
    </body></html>"""
    res = _fetch(monkeypatch, html)
    assert res.status == "ok"
    assert [i.title for i in res.items] == ["某某股份有限公司2026年半年度报告摘要"]
    assert "3 boilerplate dropped" in res.note


def test_a_web_server_default_page_is_an_error_not_content(monkeypatch):
    """ChinaBond answered the server with nginx's welcome page; its two vendor
    links were stored as 国债拍卖 calendar entries."""
    html = ("<html><head><title>Welcome to nginx!</title></head><body>"
            "<a href='http://nginx.org/'>nginx.org</a>"
            "<a href='http://nginx.com/'>nginx.com</a></body></html>")
    res = _fetch(monkeypatch, html, url="https://www.chinabond.com.cn/")
    assert res.status == "error" and "default page" in res.note
    assert res.items == []


def test_a_whole_article_in_one_anchor_keeps_a_readable_title(monkeypatch):
    body = "2026胡润中国民营地产超级联赛" + "正文" * 900
    html = f"<html><body><main><a href='/reports/Detail?num=RI13'>{body}</a></main></body></html>"
    res = _fetch(monkeypatch, html, url="https://www.hurun.net/zh-CN/reports")
    item = res.items[0]
    assert len(item.title) <= 160 and item.title.startswith("2026胡润中国民营地产超级联赛")
    assert item.summary == body           # nothing lost, just moved


@pytest.mark.parametrize("url,expected", [
    ("http://www.cninfo.com.cn/new/disclosure/detail?stockCode=600226&announcementTime=2026-08-14",
     "2026-08-14"),
    ("http://www.cninfo.com.cn/new/disclosure/detail?stockCode=600226", None),
])
def test_cninfo_disclosure_date_comes_from_the_link(url, expected):
    got = _cninfo_published(url)
    assert (got.date().isoformat() if got else None) == expected
