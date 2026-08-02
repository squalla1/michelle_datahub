"""API fetcher — dispatches to per-provider plugins keyed off the `方式` value
(GDELT DOC API, FMP API, AKShare API, ArXiv API, twitterapi.io, FRED, ...).

GDELT and ArXiv are implemented as real, key-free examples. Providers that need
credentials return status="skipped" with a clear note until a key is configured;
add new providers by registering a callable in PROVIDERS."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Callable

import httpx

from ..config import get_settings
from ..models import utcnow
from .base import Fetcher, FetchResult, RawItem

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
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
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


def _fmp_route(source) -> list[tuple[str, dict, str]]:
    """Map a registry row to FMP /stable calls: [(endpoint, params, kind)]."""
    l1 = (source.l1_category or "")
    l2 = (source.l2_category or "")
    name = (source.name or "")
    if source.module == "calendar":
        if "分红" in l1 or "拆股" in l1:
            return [("dividends-calendar", {}, "dividend"), ("splits-calendar", {}, "split")]
        if "IPO" in l1:
            return [("ipos-calendar", {}, "ipo")]
        if "经济" in l1:
            return [("economic-calendar", {}, "economic")]
        return [("earnings-calendar", {}, "earnings")]  # 财报日历 / 公司IR事件
    if source.module == "events":
        plan = [("mergers-acquisitions-latest", {}, "ma")]
        if "资本" in l1 or "IPO" in name:
            plan.append(("ipos-calendar", {}, "ipo"))
        return plan
    if source.module == "market":
        if "债" in l1:
            return [("treasury-rates", {}, "treasury")]
        if "Forex" in l1:
            return [("batch-forex-quotes", {}, "quotes")]
        if "Crypto" in l1:
            return [("batch-crypto-quotes", {}, "quotes")]
        if "Commodities" in l1:
            return [("batch-commodity-quotes", {}, "quotes")]
        if "指数" in name or "ETF" in name:
            return [("batch-index-quotes", {}, "quotes")]
        for key, code in _FMP_EXCHANGES:
            if key in l2:
                return [("batch-exchange-quote", {"exchange": code}, "quotes")]
        return [("most-actives", {}, "quotes")]  # 全球综合
    if source.module == "company":
        # Needs a watchlist: comma-separated tickers in the registry 账号 column.
        symbols = [s.strip() for s in (source.account or "").split(",") if s.strip()]
        return [("quote", {"symbol": s}, "quotes") for s in symbols]
    return []


def _fmp_items(kind: str, data, cap: int) -> list[RawItem]:
    now = utcnow().replace(microsecond=0)
    today = now.strftime("%Y-%m-%d")
    items: list[RawItem] = []
    rows = data if isinstance(data, list) else []
    if kind == "quotes":
        # Full exchange lists are alphabetical — keep the most-traded names.
        rows = sorted(rows, key=lambda r: r.get("volume") or 0, reverse=True)[:cap]
        for r in rows:
            sym = r.get("symbol")
            if not sym:
                continue
            payload = {k: r[k] for k in
                       ("symbol", "price", "change", "changePercentage", "volume",
                        "marketCap", "name", "exchange") if r.get(k) is not None}
            change = r.get("change")
            title = f"{r.get('name') or sym} {r.get('price')}"
            if change is not None:
                title += f" ({'+' if change >= 0 else ''}{change})"
            items.append(RawItem(
                external_id=f"q:{sym}:{today}", title=title,
                published_at=now, payload=payload))
    elif kind in ("earnings", "dividend", "split", "ipo"):
        label = {"earnings": "财报", "dividend": "分红", "split": "拆股", "ipo": "IPO"}[kind]
        for r in rows[:cap]:
            sym, date = r.get("symbol"), r.get("date")
            if not sym:
                continue
            payload = {k: v for k, v in r.items() if v is not None}
            payload.setdefault("event_date", date)
            items.append(RawItem(
                external_id=f"{kind}:{sym}:{date}",
                title=f"{r.get('company') or sym} {label} {date}",
                published_at=_parse_dt(date), payload=payload))
    elif kind == "economic":
        for r in rows[:cap]:
            date, event = r.get("date"), r.get("event")
            if not event:
                continue
            items.append(RawItem(
                external_id=f"eco:{r.get('country')}:{event}:{date}",
                title=f"[{r.get('country')}] {event}",
                published_at=_parse_dt(date),
                payload={k: v for k, v in r.items() if v is not None}))
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
    plan = _fmp_route(source)
    if not plan:
        return FetchResult(status="skipped",
                           note="FMP: no endpoint mapping (company rows need "
                                "comma-separated tickers in the 账号 column)")
    cap = fetcher.settings.max_items_per_fetch
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
        items.extend(_fmp_items(kind, data, cap))
    return FetchResult(items=items[:cap], status="ok",
                       note=None if items else "fmp: empty response")


# ---- FRED (St. Louis Fed, free key) ----------------------------------------

_FRED_DEFAULT_SERIES = ("DFF", "DGS2", "DGS10", "T10Y2Y")
_FRED_TREASURY_SERIES = ("DGS1MO", "DGS3MO", "DGS2", "DGS10", "DGS30")


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
                        "sort_order": "desc", "limit": "24"})
            resp.raise_for_status()
            obs = resp.json().get("observations", [])
        except (httpx.HTTPError, ValueError) as exc:
            return FetchResult(status="error", note=f"fred {sid}: {exc}")
        for o in obs:
            if o.get("value") in (None, "."):
                continue
            items.append(RawItem(
                external_id=f"{sid}:{o['date']}",
                title=f"{sid} = {o['value']} ({o['date']})",
                url=f"https://fred.stlouisfed.org/series/{sid}",
                published_at=_parse_dt(o.get("date")),
                payload={"indicator": sid, "value": float(o["value"]), "period": o["date"]}))
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


# method keyword (lowercase substring) -> provider function
PROVIDERS: dict[str, ProviderFn] = {
    "gdelt": _gdelt,
    "arxiv": _arxiv,
    "fmp": _fmp,
    "fred": _fred,
    "finnhub": _finnhub,
    "twitterapi.io": _needs_key("twitterapi.io", "twitterapi_io_key"),
    "acled": _needs_key("ACLED", "acled_api_key"),
}


class ApiFetcher(Fetcher):
    method_keywords = ("api", "gdelt", "arxiv", "akshare", "twitterapi")

    # Hybrid methods such as "NewsAPI/官方RSS" or "OFAC API/RSS" contain "api"
    # but carry a real feed URL. When we have no provider plugin for them, defer
    # to the RSS fetcher instead of claiming and skipping them here.
    _rss_fallback_keywords = ("rss", "google news", "feed", "atom", "hnrss")

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = httpx.Client(
            timeout=self.settings.request_timeout,
            headers={"User-Agent": self.settings.user_agent},
            follow_redirects=True,
        )

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
