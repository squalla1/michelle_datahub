"""Pure-unit tests for the FMP/FRED provider routing (no network)."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from datahub.config import get_settings
from datahub.fetchers.api import (
    _calendar_windows,
    _fmp_items,
    _fmp_route,
    _fred_series,
    _parse_dt,
)
from datahub.models import utcnow


def _src(module, l1=None, l2=None, name="", url=None, account=None):
    return SimpleNamespace(module=module, l1_category=l1, l2_category=l2,
                           name=name, url=url, account=account)


def test_fmp_route_calendar():
    assert _fmp_route(_src("calendar", l1="1. 财报日历")) == [("earnings-calendar", {}, "earnings")]
    assert _fmp_route(_src("calendar", l1="2. 分红/拆股")) == [
        ("dividends-calendar", {}, "dividend"), ("splits-calendar", {}, "split")]
    assert _fmp_route(_src("calendar", l1="3. IPO/上市")) == [("ipos-calendar", {}, "ipo")]
    assert _fmp_route(_src("calendar", l1="7. 经济数据日历")) == [("economic-calendar", {}, "economic")]


def test_calendar_route_asks_for_a_forward_window():
    """Without from/to, FMP answers with the current week only — which is why
    the calendar module held 0 events dated after today."""
    settings = get_settings()
    plan = _fmp_route(_src("calendar", l1="1. 财报日历"), settings)
    today = utcnow().date().isoformat()
    starts = [p[1]["from"] for p in plan]
    ends = [p[1]["to"] for p in plan]
    assert all(ep == "earnings-calendar" for ep, _, _ in plan)
    assert min(starts) < today < max(ends)
    assert max(ends) >= (utcnow().date() + timedelta(days=21)).isoformat()
    # Windows are chunked and contiguous: one month-wide request gets truncated
    # at 4,000 rows in date-DESC order, dropping exactly the near-term dates.
    assert len(plan) > 1
    for earlier, later in zip(plan, plan[1:]):
        assert earlier[1]["to"] < later[1]["from"]


def test_calendar_windows_cover_the_whole_span_without_gaps():
    windows = _calendar_windows(get_settings())
    for earlier, later in zip(windows, windows[1:]):
        assert date.fromisoformat(later["from"]) - date.fromisoformat(earlier["to"]) == timedelta(days=1)


def test_calendar_cap_drops_the_far_future_not_next_week():
    rows = [{"symbol": f"S{d}", "date": f"2026-09-{d:02d}"} for d in range(1, 20)]
    items = _fmp_items("earnings", list(reversed(rows)), cap=3)
    assert [i.payload["event_date"] for i in items] == ["2026-09-01", "2026-09-02", "2026-09-03"]


def test_economic_events_declare_their_time_basis():
    eco = _fmp_items("economic", [{"country": "US", "event": "CPI", "date": "2026-08-12 12:30:00"}], cap=5)
    assert eco[0].payload["event_timezone"] == "UTC"


def test_fmp_route_market():
    assert _fmp_route(_src("market", l1="2. 二级市场", l2="美股 NYSE")) == [
        ("batch-exchange-quote", {"exchange": "NYSE"}, "equity")]
    assert _fmp_route(_src("market", l1="2. 二级市场", l2="港交所 HKEX")) == [
        ("batch-exchange-quote", {"exchange": "HKSE"}, "equity")]
    assert _fmp_route(_src("market", l1="3. 债", l2="全球主权债")) == [("treasury-rates", {}, "treasury")]
    assert _fmp_route(_src("market", l1="5. Forex", l2="主要货币对")) == [("batch-forex-quotes", {}, "forex")]
    assert _fmp_route(_src("market", l1="6. Crypto", l2="聚合")) == [("batch-crypto-quotes", {}, "crypto")]
    assert _fmp_route(_src("market", l1="2. 二级市场", l2="全球综合", name="全球指数/ETF")) == [
        ("batch-index-quotes", {}, "index")]


def test_fmp_route_company_needs_watchlist():
    assert _fmp_route(_src("company")) == []
    assert _fmp_route(_src("company", account="AAPL, MSFT")) == [
        ("quote", {"symbol": "AAPL"}, "equity"), ("quote", {"symbol": "MSFT"}, "equity")]


def test_fmp_quotes_sorted_by_volume_and_capped():
    data = [{"symbol": "A", "price": 1, "volume": 10},
            {"symbol": "B", "price": 2, "volume": 300},
            {"symbol": "C", "price": 3, "volume": 200}]
    items = _fmp_items("equity", data, cap=2)
    assert [i.payload["symbol"] for i in items] == ["B", "C"]
    assert items[0].external_id.startswith("q:B:")
    assert items[0].payload["volume"] == 300
    assert items[0].payload["asset_class"] == "股票"


def test_benchmark_symbols_survive_a_thin_volume_day():
    """FMP's synthetic FX volume moved EURUSD out of the top 100 from one fetch
    to the next, so the pair looked like it had stopped updating."""
    data = [{"symbol": "XAUTRY", "price": 1, "volume": 2_000_000},
            {"symbol": "ARSZAR", "price": 2, "volume": 1_000_000},
            {"symbol": "EURUSD", "price": 1.1, "volume": 12},
            {"symbol": "USDJPY", "price": 150.0, "volume": 0}]
    items = _fmp_items("forex", data, cap=3)
    symbols = [i.payload["symbol"] for i in items]
    assert symbols[:2] == ["EURUSD", "USDJPY"]      # benchmarks pinned first
    assert items[0].payload["asset_class"] == "外汇" and items[0].payload["benchmark"] is True
    assert "XAUTRY" in symbols                       # cap filled by volume


def test_registry_account_overrides_the_benchmark_list():
    data = [{"symbol": "EURUSD", "price": 1.1, "volume": 1},
            {"symbol": "USDTRY", "price": 40.0, "volume": 2}]
    items = _fmp_items("forex", data, cap=2, benchmarks=("USDTRY",))
    assert [i.payload["symbol"] for i in items] == ["USDTRY", "EURUSD"]


def test_fred_series_resolution():
    # series id parsed straight out of the registry URL
    assert _fred_series(_src("macro", url="https://fred.stlouisfed.org/series/EXHOSLUSM495S")) == [
        "EXHOSLUSM495S"]
    # explicit comma list in 账号 wins over keywords
    assert _fred_series(_src("macro", account="DFF,CPIAUCSL")) == ["DFF", "CPIAUCSL"]
    # treasury keyword set
    assert "DGS30" in _fred_series(_src("market", l2="美国国债", name="FRED Treasury Rates"))
    # generic default basket: rates + inflation + labour + activity + money
    default = _fred_series(_src("macro", l2="货币/利率", name="Fed FRED"))
    assert default[:4] == ["DFF", "DGS2", "DGS10", "T10Y2Y"]
    for series in ("CPIAUCSL", "UNRATE", "PAYEMS", "M2SL"):
        assert series in default


def test_parse_dt():
    assert _parse_dt("2026-07-31").day == 31
    assert _parse_dt("2026-07-31 03:00:00").hour == 3
    assert _parse_dt("2026-08-05T08:05:15Z").hour == 8  # StockTwits ISO form
    assert _parse_dt(None) is None
    assert _parse_dt("n/a") is None


def test_calendar_items_labelled_by_event_kind_not_registry():
    """Registry L2 would tag every row 美股; the feeds are global (8031.T)."""
    items = _fmp_items("earnings", [{"symbol": "8031.T", "date": "2026-08-03"}], cap=10)
    assert items[0].payload["calendar_type"] == "财报"
    assert items[0].payload["event_date"] == "2026-08-03"
    assert _fmp_items("dividend", [{"symbol": "AAPL", "date": "2026-08-03"}], cap=10)[0] \
        .payload["calendar_type"] == "分红"
    eco = _fmp_items("economic", [{"country": "BE", "event": "CPI", "date": "2026-07-30"}], cap=10)
    assert eco[0].payload["calendar_type"] == "经济"


def test_treasury_newest_curve_survives_the_cap():
    rows = [{"date": f"2026-07-{d:02d}", "month3": 3.9} for d in range(20, 32)]
    items = _fmp_items("treasury", rows, cap=100)
    assert [i.payload["date"] for i in items] == [
        "2026-07-31", "2026-07-30", "2026-07-29", "2026-07-28", "2026-07-27"]
