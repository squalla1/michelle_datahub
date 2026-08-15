"""Best-effort HTML scraper for 爬虫 / 官方(爬取) sources.

Generic implementation: fetches the page and extracts *content* links as items.
"Content" is the hard part — a naive anchor sweep returns the site's skeleton
(nav entries, footer ICP numbers, "投资者_1478879221000" profile links, service
menus), which is what filled several company/calendar sources with junk. The
generic path therefore drops boilerplate regions, off-site links and obvious
chrome before falling back to whatever is left, and refuses to store anything
when the page it received is a web-server default page.

Site-specific extraction is registered per host in `_SITE_HANDLERS`; SEC EDGAR
and 巨潮资讯 have one because their generic output was unusable.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from ..config import get_settings
from ..models import to_naive_utc
from .base import Fetcher, FetchResult, RawItem, http_options

# Regions and class/id fragments that hold site chrome rather than content.
_CHROME_TAGS = ("nav", "header", "footer", "aside", "form")
_CHROME_PATTERN = re.compile(
    r"nav|menu|footer|header|sidebar|side-bar|breadcrumb|crumb|banner|social|"
    r"share|subscribe|cookie|login|signin|copyright|beian|toolbar|topbar|"
    r"skip|search-box",
    re.I,
)
# Hosts that only ever appear as chrome (filing/ICP badges, CDN vendor links).
_JUNK_HOSTS = (
    "beian.miit.gov.cn", "beian.gov.cn", "nginx.org", "nginx.com",
    "www.miitbeian.gov.cn", "twitter.com", "x.com", "facebook.com",
    "linkedin.com", "instagram.com", "youtube.com", "weibo.com", "t.me",
)
# Pages a misrouted/blocked request lands on. Storing their links is what put
# "nginx.org" into the 国债拍卖 calendar.
_DEFAULT_PAGE_MARKERS = (
    "welcome to nginx", "apache2 ubuntu default page", "it works!",
    "iis windows server", "test page for the", "default web site page",
)
_MAX_TITLE = 160
# An article URL almost always carries a date segment or a long slug. When a
# page offers such links they *are* its content, and everything else on it is
# furniture — Motley Fool's transcript index is 90% quote widgets and service
# menus around 20 real transcripts.
_ARTICLE_PATH = re.compile(r"/(19|20)\d{2}/\d{2}/|/[a-z0-9]+(?:-[a-z0-9]+){3,}")
# Hosts that render their list through XHR: the served HTML has no content
# links at all, only the shell. Scraping them yields the shell (profile links,
# nav labels), so refuse instead — these need a dedicated parser or an API.
_JS_APP_HOSTS = {
    "sns.sseinfo.com": "上交所e互动 loads its Q&A over XHR; the served page carries only user links",
    "hkexnews.hk": "HKEX News is a JS search app; use its title-search JSON endpoint",
    "guba.eastmoney.com": "股吧 renders posts client-side",
}


def _is_chrome(anchor) -> bool:
    """True when the anchor sits in a nav/footer/aside region."""
    for parent in anchor.parents:
        name = getattr(parent, "name", None)
        if name in _CHROME_TAGS:
            return True
        if name in (None, "[document]", "html"):
            continue
        attrs = parent.attrs if hasattr(parent, "attrs") else {}
        marker = f"{attrs.get('id', '')} {' '.join(attrs.get('class', []) or [])}"
        if marker.strip() and _CHROME_PATTERN.search(marker):
            return True
    return False


def _registrable(host: str) -> str:
    """Crude eTLD+1 ("www.sse.com.cn" -> "sse.com.cn"). Enough to tell a site's
    own links from outbound ones; no public-suffix list dependency."""
    parts = [p for p in host.lower().split(".") if p]
    if len(parts) <= 2:
        return ".".join(parts)
    if parts[-1] in ("cn", "uk", "jp", "hk", "au", "br", "in") and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _edgar_items(source, settings) -> FetchResult:
    """SEC EDGAR browse pages, via their Atom output.

    The HTML page is a search form whose links are per-company query URLs, so
    the generic scraper stored CIK query strings ("333-275606-04") as titles.
    The same endpoint with `output=atom` returns one entry per filing carrying
    the company name, the form type, the filing date and the filing's own URL.
    SEC blocks undeclared bots, hence `sec_user_agent`."""
    import feedparser

    url = source.url or ""
    if "output=atom" not in url:
        url += ("&" if "?" in url else "?") + "output=atom"
    # Unfiltered, `getcurrent` is dominated by Form 4 insider reports. The
    # registry row is the IPO/lock-up one, so ask for the registration forms it
    # is actually about (`type=` is a prefix match: S-1 covers S-1/A too).
    context = f"{source.l1_category or ''}{source.name or ''}"
    types = ["S-1", "S-11", "424B"] if ("IPO" in context or "解禁" in context) else [None]

    entries, blocked = [], False
    for form in types:
        feed_url = url + (f"&type={form}" if form else "")
        try:
            resp = httpx.get(feed_url, **http_options(settings, user_agent=settings.sec_user_agent))
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            return FetchResult(status="error", note=f"edgar: {exc}")
        feed = feedparser.parse(resp.content)
        blocked = blocked or not getattr(feed, "version", "")
        entries.extend(feed.entries)
    if not entries:
        return FetchResult(status="error" if blocked else "ok",
                           note="edgar: no entries (blocked or empty result set)")

    items = []
    for e in entries:
        title = (e.get("title") or "").strip()          # "S-1 - ACME Inc. (0001234567) (Filer)"
        form, _, rest = title.partition(" - ")
        company = re.sub(r"\s*\(\d{7,10}\)\s*\(.*?\)\s*$", "", rest).strip() or None
        cik = (re.search(r"\((\d{7,10})\)", rest) or [None, None])[1]
        published = None
        if e.get("updated_parsed"):
            from datetime import datetime as _dt

            published = to_naive_utc(_dt(*e.updated_parsed[:6]))
        payload = {"form_type": form.strip() or None, "companyName": company, "cik": cik}
        items.append(RawItem(
            external_id=e.get("id") or e.get("link") or title,
            title=f"{company or rest.strip()} {form.strip()}".strip(),
            url=e.get("link"),
            summary=re.sub(r"<[^>]+>", " ", e.get("summary") or "").strip() or None,
            published_at=published,
            payload={k: v for k, v in payload.items() if v},
        ))
    return FetchResult(items=items, status="ok", note="edgar atom")


_URL_DATE = re.compile(r"(20\d{2})[-/_]?(0[1-9]|1[0-2])[-/_]?(0[1-9]|[12]\d|3[01])")


def _date_in_url(url: str):
    """Publication date from the URL itself — `/2026/08/14/slug`,
    `fomcpresconf20211103.htm`. Most static publishers put it there, and it is
    the only date a link-list page offers before the article is fetched."""
    from datetime import datetime as _dt

    match = _URL_DATE.search(urlparse(url).path)
    if not match:
        return None
    try:
        return _dt(*(int(g) for g in match.groups()))
    except ValueError:
        return None


def _cninfo_published(url: str):
    """巨潮 detail links carry the disclosure date as a query parameter."""
    stamp = parse_qs(urlparse(url).query).get("announcementTime", [None])[0]
    if not stamp:
        return None
    from datetime import datetime as _dt

    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return _dt.strptime(stamp[: len("2026-01-01 00:00:00")], fmt)
        except ValueError:
            continue
    return None


# host substring -> full-page handler
_SITE_HANDLERS = {"sec.gov": _edgar_items}
# host substring -> per-item published_at resolver
_DATE_FROM_URL = {"cninfo.com.cn": _cninfo_published}


class ScraperFetcher(Fetcher):
    method_keywords = ("爬虫", "爬取", "scrape", "crawl")

    def __init__(self) -> None:
        self._settings = get_settings()

    def fetch(self, source) -> FetchResult:
        if not source.url or not source.url.startswith("http"):
            return FetchResult(status="skipped", note="no fetchable URL")
        host = urlparse(source.url).netloc.lower()
        for needle, handler in _SITE_HANDLERS.items():
            if needle in host:
                return handler(source, self._settings)
        for needle, why in _JS_APP_HOSTS.items():
            if needle in host:
                return FetchResult(status="skipped", note=f"needs a dedicated parser: {why}")
        try:
            resp = httpx.get(source.url, **http_options(self._settings))
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            return FetchResult(status="error", note=f"http: {exc}")

        soup = BeautifulSoup(resp.text, "html.parser")
        page_title = (soup.title.get_text(strip=True) if soup.title else "").lower()
        if any(marker in page_title for marker in _DEFAULT_PAGE_MARKERS):
            # The origin answered with a stock server page (geo-block, misrouted
            # vhost, outage). Report it instead of ingesting the vendor's links.
            return FetchResult(status="error",
                               note=f"web server default page, not the source site ({page_title[:60]})")

        site = _registrable(urlparse(str(resp.url)).netloc)
        date_from_url = next((fn for needle, fn in _DATE_FROM_URL.items() if needle in host),
                             _date_in_url)
        seen: set[str] = set()
        items: list[RawItem] = []
        dropped = 0
        for a in soup.find_all("a", href=True):
            text = a.get_text(" ", strip=True)
            if not text or len(text) < 8:
                continue
            href = urljoin(str(resp.url), a["href"])
            parsed = urlparse(href)
            if parsed.scheme not in ("http", "https"):
                continue
            if not parsed.path.strip("/") and not parsed.query:
                dropped += 1  # site root / bare fragment: a logo or footer link
                continue
            if any(j in parsed.netloc.lower() for j in _JUNK_HOSTS):
                dropped += 1
                continue
            if _registrable(parsed.netloc) != site:
                dropped += 1  # outbound link: chrome or third-party content
                continue
            if href in seen:
                continue
            if _is_chrome(a):
                dropped += 1
                continue
            seen.add(href)
            # Some sites wrap a whole article in one <a>; keep the title short
            # and preserve the full text as the summary.
            title, summary = text[:_MAX_TITLE], (text if len(text) > _MAX_TITLE else None)
            items.append(
                RawItem(
                    external_id=hashlib.sha1(href.encode()).hexdigest(),
                    title=title,
                    url=href,
                    summary=summary,
                    published_at=date_from_url(href) or _date_in_url(href),
                )
            )
            if len(items) >= self._settings.max_items_per_fetch:
                break

        articles = [i for i in items if _ARTICLE_PATH.search(urlparse(i.url).path)]
        if articles and len(articles) < len(items):
            dropped += len(items) - len(articles)
            items = articles
        note = f"generic link extraction ({len(items)} kept, {dropped} boilerplate dropped)"
        return FetchResult(items=items, status="ok", note=note)
