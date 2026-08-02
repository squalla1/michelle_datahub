"""Pure-unit tests for the FMP/FRED provider routing (no network)."""

from __future__ import annotations

from types import SimpleNamespace

from datahub.fetchers.api import _fmp_items, _fmp_route, _fred_series, _parse_dt


def _src(module, l1=None, l2=None, name="", url=None, account=None):
    return SimpleNamespace(module=module, l1_category=l1, l2_category=l2,
                           name=name, url=url, account=account)


def test_fmp_route_calendar():
    assert _fmp_route(_src("calendar", l1="1. 财报日历")) == [("earnings-calendar", {}, "earnings")]
    assert _fmp_route(_src("calendar", l1="2. 分红/拆股")) == [
        ("dividends-calendar", {}, "dividend"), ("splits-calendar", {}, "split")]
    assert _fmp_route(_src("calendar", l1="3. IPO/上市")) == [("ipos-calendar", {}, "ipo")]
    assert _fmp_route(_src("calendar", l1="7. 经济数据日历")) == [("economic-calendar", {}, "economic")]


def test_fmp_route_market():
    assert _fmp_route(_src("market", l1="2. 二级市场", l2="美股 NYSE")) == [
        ("batch-exchange-quote", {"exchange": "NYSE"}, "quotes")]
    assert _fmp_route(_src("market", l1="2. 二级市场", l2="港交所 HKEX")) == [
        ("batch-exchange-quote", {"exchange": "HKSE"}, "quotes")]
    assert _fmp_route(_src("market", l1="3. 债", l2="全球主权债")) == [("treasury-rates", {}, "treasury")]
    assert _fmp_route(_src("market", l1="5. Forex", l2="主要货币对")) == [("batch-forex-quotes", {}, "quotes")]
    assert _fmp_route(_src("market", l1="6. Crypto", l2="聚合")) == [("batch-crypto-quotes", {}, "quotes")]
    assert _fmp_route(_src("market", l1="2. 二级市场", l2="全球综合", name="全球指数/ETF")) == [
        ("batch-index-quotes", {}, "quotes")]


def test_fmp_route_company_needs_watchlist():
    assert _fmp_route(_src("company")) == []
    assert _fmp_route(_src("company", account="AAPL, MSFT")) == [
        ("quote", {"symbol": "AAPL"}, "quotes"), ("quote", {"symbol": "MSFT"}, "quotes")]


def test_fmp_quotes_sorted_by_volume_and_capped():
    data = [{"symbol": "A", "price": 1, "volume": 10},
            {"symbol": "B", "price": 2, "volume": 300},
            {"symbol": "C", "price": 3, "volume": 200}]
    items = _fmp_items("quotes", data, cap=2)
    assert [i.payload["symbol"] for i in items] == ["B", "C"]
    assert items[0].external_id.startswith("q:B:")
    assert items[0].payload["volume"] == 300


def test_fred_series_resolution():
    # series id parsed straight out of the registry URL
    assert _fred_series(_src("macro", url="https://fred.stlouisfed.org/series/EXHOSLUSM495S")) == [
        "EXHOSLUSM495S"]
    # explicit comma list in 账号 wins over keywords
    assert _fred_series(_src("macro", account="DFF,CPIAUCSL")) == ["DFF", "CPIAUCSL"]
    # treasury keyword set
    assert "DGS30" in _fred_series(_src("market", l2="美国国债", name="FRED Treasury Rates"))
    # generic rates default
    assert _fred_series(_src("macro", l2="货币/利率", name="Fed FRED")) == [
        "DFF", "DGS2", "DGS10", "T10Y2Y"]


def test_parse_dt():
    assert _parse_dt("2026-07-31").day == 31
    assert _parse_dt("2026-07-31 03:00:00").hour == 3
    assert _parse_dt(None) is None
    assert _parse_dt("n/a") is None
