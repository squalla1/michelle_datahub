"""API fetcher — dispatches to per-provider plugins keyed off the `方式` value
(GDELT DOC API, FMP API, AKShare API, ArXiv API, twitterapi.io, FRED, ...).

GDELT and ArXiv are implemented as real, key-free examples. Providers that need
credentials return status="skipped" with a clear note until a key is configured;
add new providers by registering a callable in PROVIDERS."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Callable

import httpx

from ..config import get_settings
from ..models import utcnow
from .base import Fetcher, FetchResult, RawItem, http_options

ProviderFn = Callable[[object, "ApiFetcher"], FetchResult]


def _hash_id(*parts: str) -> str:
    return hashlib.sha1("|".join(p or "" for p in parts).encode()).hexdigest()


def _gdelt(source, fetcher: "ApiFetcher") -> FetchResult:
    """GDELT 2.0 DOC API — free article search. Uses the source name/category as
    the query when the row carries no explicit query in `account`."""
    query = source.account or source.l2_category or source.name
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": str(min(fetcher.settings.max_items_per_fetch, 75)),
        "sort": "DateDesc",
    }
    try:
        resp = fetcher.client.get(
            "https://api.gdeltproject.org/api/v2/doc/doc", params=params
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        return FetchResult(status="error", note=f"gdelt: {exc}")

    items = []
    for art in data.get("articles", []):
        items.append(
            RawItem(
                external_id=art.get("url") or _hash_id(art.get("title", "")),
                title=art.get("title"),
                url=art.get("url"),
                summary=art.get("domain"),
                published_at=_gdelt_time(art.get("seendate")),
                payload={"language": art.get("language"), "sourcecountry": art.get("sourcecountry")},
            )
        )
    return FetchResult(items=items, status="ok")


def _gdelt_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # GDELT times are UTC; keep naive (see models.utcnow rationale).
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ")
    except ValueError:
        return None


def _arxiv(source, fetcher: "ApiFetcher") -> FetchResult:
    """ArXiv Atom API — free. Delegates parsing to feedparser."""
    import feedparser

    query = source.account or source.l2_category or "cs.AI"
    try:
        resp = fetcher.client.get(
            "http://export.arxiv.org/api/query",
            params={"search_query": f"all:{query}", "max_results": "50", "sortBy": "submittedDate", "sortOrder": "descending"},
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        return FetchResult(status="error", note=f"arxiv: {exc}")
    feed = feedparser.parse(resp.content)
    items = [
        RawItem(
            external_id=e.get("id", _hash_id(e.get("title", ""))),
            title=e.get("title"),
            url=e.get("link"),
            summary=e.get("summary"),
        )
        for e in feed.entries
    ]
    return FetchResult(items=items, status="ok")


def _needs_key(provider: str, key_attr: str) -> ProviderFn:
    def _fn(source, fetcher: "ApiFetcher") -> FetchResult:
        if getattr(fetcher.settings, key_attr, None):
            return FetchResult(status="skipped", note=f"{provider} plugin not implemented yet")
        return FetchResult(status="skipped", note=f"{provider} requires DATAHUB_{key_attr.upper()}")
    return _fn


def _parse_dt(value: str | None) -> datetime | None:
    """Parse the provider date formats into naive UTC."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[: len("2026-01-01 00:00:00")], fmt)
        except ValueError:
            continue
    return None


# ---- FMP (financialmodelingprep.com /stable API, paid key) ------------------

_FMP_BASE = "https://financialmodelingprep.com/stable"

# l2_category substring -> FMP exchange code (verified live 2026-08-02;
# Euronext maps to its Paris leg, KRX to FMP's KSC code).
_FMP_EXCHANGES = (
    ("NYSE", "NYSE"), ("Nasdaq", "NASDAQ"), ("LSE", "LSE"), ("TSX", "TSX"),
    ("NSE", "NSE"), ("JPX", "JPX"), ("HKEX", "HKSE"), ("KRX", "KSC"),
    ("Euronext", "PAR"),
)


def _calendar_windows(settings) -> list[dict]:
    """[{from,to}, ...] covering [today-lookback, today+lookahead] in chunks.

    One request for the whole span is not enough: FMP caps a calendar response
    at 4,000 rows *in date-descending order*, so a month-wide earnings query
    returns only the far end and the next three weeks come back empty — which is
    why the calendar module held history only."""
    today = utcnow().date()
    start = today - timedelta(days=settings.calendar_lookback_days)
    end = today + timedelta(days=settings.calendar_lookahead_days)
    step = max(1, settings.calendar_window_chunk_days)
    windows = []
    cursor = start
    while cursor <= end:
        stop = min(cursor + timedelta(days=step - 1), end)
        windows.append({"from": cursor.isoformat(), "to": stop.isoformat()})
        cursor = stop + timedelta(days=1)
    return windows


def _fmp_route(source, settings=None) -> list[tuple[str, dict, str]]:
    """Map a registry row to FMP /stable calls: [(endpoint, params, kind)]."""
    l1 = (source.l1_category or "")
    l2 = (source.l2_category or "")
    name = (source.name or "")
    if source.module == "calendar":
        windows = _calendar_windows(settings) if settings else [{}]
        if "分红" in l1 or "拆股" in l1:
            endpoints = [("dividends-calendar", "dividend"), ("splits-calendar", "split")]
        elif "IPO" in l1:
            endpoints = [("ipos-calendar", "ipo")]
        elif "经济" in l1:
            endpoints = [("economic-calendar", "economic")]
        else:
            endpoints = [("earnings-calendar", "earnings")]  # 财报日历 / 公司IR事件
        return [(ep, w, kind) for ep, kind in endpoints for w in windows]
    if source.module == "events":
        plan = [("mergers-acquisitions-latest", {}, "ma")]
        if "资本" in l1 or "IPO" in name:
            plan.append(("ipos-calendar", {}, "ipo"))
        return plan
    if source.module == "market":
        if "债" in l1:
            return [("treasury-rates", {}, "treasury")]
        if "Forex" in l1:
            return [("batch-forex-quotes", {}, "forex")]
        if "Crypto" in l1:
            return [("batch-crypto-quotes", {}, "crypto")]
        if "Commodities" in l1:
            return [("batch-commodity-quotes", {}, "commodity")]
        if "指数" in name or "ETF" in name:
            return [("batch-index-quotes", {}, "index")]
        for key, code in _FMP_EXCHANGES:
            if key in l2:
                return [("batch-exchange-quote", {"exchange": code}, "equity")]
        return [("most-actives", {}, "equity")]  # 全球综合
    if source.module == "company":
        # Needs a watchlist: comma-separated tickers in the registry 账号 column.
        symbols = [s.strip() for s in (source.account or "").split(",") if s.strip()]
        return [("quote", {"symbol": s}, "equity") for s in symbols]
    return []


# Quote kinds -> (asset class written to payload, benchmark symbols).
#
# The batch endpoints return the whole universe (1,550 FX pairs, 280 futures);
# keeping the top N by volume alone dropped the benchmarks product pages are
# built on — FMP's synthetic FX volume put EURUSD at rank 72 one day and outside
# the top 100 the next, so it looked like the symbol had stopped updating, and
# USDJPY (volume 0) was never ingested at all. Benchmarks are always kept, the
# rest of the cap is filled by volume. The registry 账号 column overrides the
# list per row.
_FMP_QUOTE_KINDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "forex": ("外汇", (
        "EURUSD", "USDJPY", "GBPUSD", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
        "USDCNH", "USDHKD", "USDKRW", "USDSGD", "USDINR", "USDTWD", "USDBRL",
        "USDMXN", "USDTRY", "USDZAR", "USDRUB", "EURGBP", "EURJPY", "EURCHF",
        "GBPJPY", "AUDJPY", "DXY",
    )),
    "crypto": ("加密货币", (
        "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD", "ADAUSD", "DOGEUSD",
        "TRXUSD", "AVAXUSD", "LTCUSD", "USDTUSD", "USDCUSD",
    )),
    "commodity": ("商品", (
        "GCUSD", "SIUSD", "PLUSD", "HGUSD", "CLUSD", "BZUSD", "NGUSD",
        "ZCUSX", "ZWUSX", "ZSUSX", "KCUSX", "SBUSX", "CCUSD", "CTUSX",
    )),
    "index": ("指数", (
        "^GSPC", "^DJI", "^IXIC", "^RUT", "^VIX", "^FTSE", "^GDAXI", "^FCHI",
        "^STOXX50E", "^N225", "^HSI", "^KS11", "^AXJO", "^BSESN", "^TNX",
    )),
    "equity": ("股票", ()),
    "quotes": ("", ()),   # legacy kind, kept so old callers still work
}


def _fmp_items(kind: str, data, cap: int, benchmarks: tuple[str, ...] = ()) -> list[RawItem]:
    now = utcnow().replace(microsecond=0)
    today = now.strftime("%Y-%m-%d")
    items: list[RawItem] = []
    rows = data if isinstance(data, list) else []
    if kind in _FMP_QUOTE_KINDS:
        asset_class, default_benchmarks = _FMP_QUOTE_KINDS[kind]
        order = [s.upper() for s in (benchmarks or default_benchmarks)]
        wanted = set(order)
        # Benchmarks first (in the order declared), then the most-traded rest.
        pinned = sorted((r for r in rows if (r.get("symbol") or "").upper() in wanted),
                        key=lambda r: order.index((r.get("symbol") or "").upper()))
        rest = sorted((r for r in rows if (r.get("symbol") or "").upper() not in wanted),
                      key=lambda r: r.get("volume") or 0, reverse=True)
        for r in (pinned + rest)[:cap]:
            sym = r.get("symbol")
            if not sym:
                continue
            payload = {k: r[k] for k in
                       ("symbol", "price", "change", "changePercentage", "volume",
                        "marketCap", "name", "exchange") if r.get(k) is not None}
            if asset_class:
                # The registry L1 would label an exchange row "二级市场", which is
                # a market segment, not an asset class. The endpoint knows better.
                payload["asset_class"] = asset_class
            if sym.upper() in wanted:
                payload["benchmark"] = True
            change = r.get("change")
            title = f"{r.get('name') or sym} {r.get('price')}"
            if change is not None:
                title += f" ({'+' if change >= 0 else ''}{change})"
            items.append(RawItem(
                external_id=f"q:{sym}:{today}", title=title,
                published_at=now, payload=payload))
    elif kind in ("earnings", "dividend", "split", "ipo"):
        label = {"earnings": "财报", "dividend": "分红", "split": "拆股", "ipo": "IPO"}[kind]
        # Ascending by event date so that when the cap bites it drops the far
        # future, not the next few days.
        rows = sorted(rows, key=lambda r: r.get("date") or "")
        for r in rows[:cap]:
            sym, date = r.get("symbol"), r.get("date")
            if not sym:
                continue
            payload = {k: v for k, v in r.items() if v is not None}
            payload.setdefault("event_date", date)
            # The registry's L2 would otherwise label every row "美股", but these
            # feeds are global (8031.T, DOMS.NS). The event kind is the truth.
            payload["calendar_type"] = label
            items.append(RawItem(
                external_id=f"{kind}:{sym}:{date}",
                title=f"{r.get('company') or sym} {label} {date}",
                published_at=_parse_dt(date), payload=payload))
    elif kind == "economic":
        rows = sorted(rows, key=lambda r: r.get("date") or "")
        for r in rows[:cap]:
            date, event = r.get("date"), r.get("event")
            if not event:
                continue
            items.append(RawItem(
                external_id=f"eco:{r.get('country')}:{event}:{date}",
                title=f"[{r.get('country')}] {event}",
                published_at=_parse_dt(date),
                # FMP stamps these in UTC (verified: July US CPI carries
                # 2026-08-12 12:30:00 = 08:30 ET, its actual release time).
                payload={**{k: v for k, v in r.items() if v is not None},
                         "calendar_type": "经济", "event_date": date,
                         "event_timezone": "UTC"}))
    elif kind == "ma":
        for r in rows[:cap]:
            target = r.get("targetedCompanyName")
            items.append(RawItem(
                external_id=f"ma:{r.get('cik')}:{r.get('targetedCik') or target}",
                title=f"{r.get('companyName')} 并购 {target}",
                url=r.get("link"),
                published_at=_parse_dt(r.get("transactionDate") or r.get("acceptedDate")),
                payload={k: v for k, v in r.items() if v is not None and k != "link"}))
    elif kind == "treasury":
        # FMP returns the window in ascending date order and lags 1-2 days —
        # sort desc so the newest curve is the one that survives the cap.
        rows = sorted(rows, key=lambda r: r.get("date") or "", reverse=True)
        for r in rows[:5]:  # daily curve snapshots
            date = r.get("date")
            items.append(RawItem(
                external_id=f"ust:{date}",
                title=f"US Treasury yield curve {date}",
                published_at=_parse_dt(date),
                payload={k: v for k, v in r.items() if v is not None}))
    return items


def _fmp(source, fetcher: "ApiFetcher") -> FetchResult:
    key = fetcher.settings.fmp_api_key
    if not key:
        return FetchResult(status="skipped", note="FMP requires DATAHUB_FMP_API_KEY")
    plan = _fmp_route(source, fetcher.settings)
    if not plan:
        return FetchResult(status="skipped",
                           note="FMP: no endpoint mapping (company rows need "
                                "comma-separated tickers in the 账号 column)")
    is_calendar = source.module == "calendar"
    cap = (fetcher.settings.calendar_max_items if is_calendar
           else fetcher.settings.max_items_per_fetch)
    # A registry row may pin its own benchmark symbols in the 账号 column.
    benchmarks = tuple(s.strip() for s in (source.account or "").split(",") if s.strip())
    # Each calendar window gets an equal share of the cap. A single global cap
    # over date-ascending rows is spent entirely on the retro window — one week
    # of global earnings is ~4,000 rows — leaving the forward schedule empty.
    per_call = max(50, cap // len(plan)) if is_calendar else cap
    items: list[RawItem] = []
    for endpoint, params, kind in plan:
        try:
            resp = fetcher.client.get(f"{_FMP_BASE}/{endpoint}", params={**params, "apikey": key})
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            return FetchResult(status="error", note=f"fmp {endpoint}: {exc}")
        if isinstance(data, dict) and data.get("Error Message"):
            return FetchResult(status="error", note=f"fmp {endpoint}: {data['Error Message'][:120]}")
        items.extend(_fmp_items(kind, data, per_call, benchmarks if not is_calendar else ()))
    if is_calendar:
        # Windows are fetched separately; present the merged schedule in event
        # order. The per-window caps already bound the total, so no global trim.
        items.sort(key=lambda i: (i.published_at or datetime.max))
        return FetchResult(items=items, status="ok",
                           note=None if items else "fmp: empty response")
    return FetchResult(items=items[:cap], status="ok",
                       note=None if items else "fmp: empty response")


# ---- FRED (St. Louis Fed, free key) ----------------------------------------

# Default macro basket for generic FRED rows: rates + inflation + labour +
# activity + money (the registry's 账号 column overrides it per row).
_FRED_DEFAULT_SERIES = (
    "DFF", "DGS2", "DGS10", "T10Y2Y",          # policy & curve
    "CPIAUCSL", "CPILFESL", "PCEPILFE",        # inflation
    "UNRATE", "PAYEMS",                        # labour
    "INDPRO", "GDPC1", "BOPGSTB",              # activity & trade
    "M2SL",                                    # money
)
_FRED_TREASURY_SERIES = ("DGS1MO", "DGS3MO", "DGS2", "DGS10", "DGS30")

# series -> (display unit, frequency). FRED reports the unit only in the series
# metadata, one extra call per series; the basket is fixed, so it is a table.
# Consumers must not infer a unit from the number.
_FRED_META: dict[str, tuple[str, str]] = {
    "DFF": ("%", "日"),
    "DGS1MO": ("%", "日"), "DGS3MO": ("%", "日"), "DGS2": ("%", "日"),
    "DGS10": ("%", "日"), "DGS30": ("%", "日"),
    "T10Y2Y": ("百分点", "日"),
    "CPIAUCSL": ("指数 (1982-84=100)", "月"),
    "CPILFESL": ("指数 (1982-84=100)", "月"),
    "PCEPILFE": ("指数 (2017=100)", "月"),
    "UNRATE": ("%", "月"),
    "PAYEMS": ("千人", "月"),
    "INDPRO": ("指数 (2017=100)", "月"),
    "GDPC1": ("十亿美元 (2017年不变价, 年化)", "季"),
    "BOPGSTB": ("百万美元", "月"),
    "M2SL": ("十亿美元", "月"),
    "EXHOSLUSM495S": ("千套 (年化)", "月"),
}


def _fred_series(source) -> list[str]:
    url = source.url or ""
    if "/series/" in url:
        sid = url.split("/series/")[1].split("/")[0].split("?")[0].strip()
        if sid:
            return [sid]
    if source.account:
        return [s.strip() for s in source.account.split(",") if s.strip()]
    text = f"{source.l1_category or ''}{source.l2_category or ''}{source.name or ''}"
    if "国债" in text or "Treasury" in text:
        return list(_FRED_TREASURY_SERIES)
    return list(_FRED_DEFAULT_SERIES)


def _fred(source, fetcher: "ApiFetcher") -> FetchResult:
    key = fetcher.settings.fred_api_key
    if not key:
        return FetchResult(status="skipped", note="FRED requires DATAHUB_FRED_API_KEY")
    items: list[RawItem] = []
    for sid in _fred_series(source):
        try:
            resp = fetcher.client.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={"series_id": sid, "api_key": key, "file_type": "json",
                        "sort_order": "desc", "limit": "36"})
            resp.raise_for_status()
            obs = resp.json().get("observations", [])
        except (httpx.HTTPError, ValueError) as exc:
            return FetchResult(status="error", note=f"fred {sid}: {exc}")
        unit, freq = _FRED_META.get(sid, (None, None))
        for o in obs:
            if o.get("value") in (None, "."):
                continue
            payload = {"indicator": sid, "value": float(o["value"]), "period": o["date"]}
            if unit:
                payload["unit"] = unit
                payload["frequency"] = freq
            items.append(RawItem(
                external_id=f"{sid}:{o['date']}",
                title=f"{sid} = {o['value']}{(' ' + unit) if unit else ''} ({o['date']})",
                url=f"https://fred.stlouisfed.org/series/{sid}",
                published_at=_parse_dt(o.get("date")),
                payload=payload))
    return FetchResult(items=items, status="ok", note=None if items else "fred: no observations")


# ---- Finnhub (free key; economic calendar needs a paid plan) ----------------

def _finnhub(source, fetcher: "ApiFetcher") -> FetchResult:
    key = fetcher.settings.finnhub_api_key
    if not key:
        return FetchResult(status="skipped", note="Finnhub requires DATAHUB_FINNHUB_API_KEY")
    try:
        resp = fetcher.client.get("https://finnhub.io/api/v1/calendar/economic",
                                  params={"token": key})
        if resp.status_code == 403:
            return FetchResult(status="error",
                               note="finnhub: economic calendar requires a paid plan "
                                    "(free tier verified 2026-08-02)")
        resp.raise_for_status()
        rows = resp.json().get("economicCalendar", [])
    except (httpx.HTTPError, ValueError) as exc:
        return FetchResult(status="error", note=f"finnhub: {exc}")
    items = [RawItem(
        external_id=f"eco:{r.get('country')}:{r.get('event')}:{r.get('time')}",
        title=f"[{r.get('country')}] {r.get('event')}",
        published_at=_parse_dt(r.get("time")),
        payload={k: v for k, v in r.items() if v is not None},
    ) for r in rows[: fetcher.settings.max_items_per_fetch]]
    return FetchResult(items=items, status="ok")


# ---- StockTwits (public API, no key) ---------------------------------------

_STOCKTWITS_TRENDING = "https://api.stocktwits.com/api/2/streams/trending.json"


def _stocktwits(source, fetcher: "ApiFetcher") -> FetchResult:
    """Trending ticker chatter. Serves both registry rows carrying 方式=公开API
    (opinion 趋势榜 and the company-side Stocktwits row); other 公开API rows are
    reported as unmapped rather than silently skipped."""
    if "stocktwits" not in (source.url or "").lower():
        return FetchResult(status="skipped",
                           note=f"no API provider plugin for '{source.method}' at {source.url}")
    try:
        resp = fetcher.client.get(_STOCKTWITS_TRENDING)
        resp.raise_for_status()
        messages = resp.json().get("messages", [])
    except (httpx.HTTPError, ValueError) as exc:
        return FetchResult(status="error", note=f"stocktwits: {exc}")

    items: list[RawItem] = []
    for m in messages[: fetcher.settings.max_items_per_fetch]:
        mid, body = m.get("id"), (m.get("body") or "").strip()
        if not mid:
            continue
        symbols = [s.get("symbol") for s in (m.get("symbols") or []) if s.get("symbol")]
        user = (m.get("user") or {}).get("username")
        payload: dict = {"platform": "StockTwits"}
        if symbols:
            payload["symbol"] = symbols[0]
            payload["symbols"] = symbols
        sentiment = ((m.get("entities") or {}).get("sentiment") or {}).get("basic")
        if sentiment:
            payload["sentiment"] = sentiment
        for p in m.get("prices") or []:
            if p.get("symbol") == payload.get("symbol") and p.get("price"):
                payload["price"] = float(p["price"])
                break
        items.append(RawItem(
            external_id=f"st:{mid}",
            title=body[:200] or f"StockTwits {mid}",
            url=f"https://stocktwits.com/{user}/message/{mid}" if user else None,
            summary=body or None,
            published_at=_parse_dt(m.get("created_at")),
            payload=payload))
    return FetchResult(items=items, status="ok",
                       note=None if items else "stocktwits: empty stream")


# method keyword (lowercase substring) -> provider function
PROVIDERS: dict[str, ProviderFn] = {
    "gdelt": _gdelt,
    "arxiv": _arxiv,
    "fmp": _fmp,
    "fred": _fred,
    "finnhub": _finnhub,
    "twitterapi.io": _needs_key("twitterapi.io", "twitterapi_io_key"),
    "acled": _needs_key("ACLED", "acled_api_key"),
    "公开api": _stocktwits,
}


class ApiFetcher(Fetcher):
    method_keywords = ("api", "gdelt", "arxiv", "akshare", "twitterapi")

    # Hybrid methods such as "NewsAPI/官方RSS" or "OFAC API/RSS" contain "api"
    # but carry a real feed URL. When we have no provider plugin for them, defer
    # to the RSS fetcher instead of claiming and skipping them here.
    _rss_fallback_keywords = ("rss", "google news", "feed", "atom", "hnrss")

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = httpx.Client(**http_options(self.settings))

    def supports(self, method: str | None) -> bool:
        if not super().supports(method):
            return False
        if self._provider_for(method) is not None:
            return True
        low = method.lower()
        return not any(k in low for k in self._rss_fallback_keywords)

    def _provider_for(self, method: str | None) -> ProviderFn | None:
        if not method:
            return None
        low = method.lower()
        for key, fn in PROVIDERS.items():
            if key in low:
                return fn
        return None

    def fetch(self, source) -> FetchResult:
        provider = self._provider_for(source.method)
        if provider is None:
            return FetchResult(
                status="skipped",
                note=f"no API provider plugin for method '{source.method}'",
            )
        return provider(source, self)
