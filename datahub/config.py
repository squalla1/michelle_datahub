"""Application configuration. Override any field via DATAHUB_* env vars or a .env file."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DATAHUB_", env_file=".env", extra="ignore"
    )

    # Storage
    database_url: str = "sqlite:///./datahub.db"

    # Catalog source (the Excel registry)
    catalog_path: str = "data/Michelle_Datasource_2026-06-02.xlsx"

    # Fetching
    request_timeout: float = 20.0
    user_agent: str = (
        "Mozilla/5.0 (compatible; MichelleDataHub/0.1; +https://example.com/bot)"
    )
    # Egress proxy for every outbound fetch (e.g. "http://127.0.0.1:7897").
    # Needed for sources that block datacenter IPs — Reddit answers 429 to the
    # server's address while the same request succeeds from a residential one.
    http_proxy: str | None = None
    # RSSHub instance. The public rsshub.app sits behind Cloudflare and answers
    # 403 to every route (verified 2026-08-05) — point this at a self-hosted
    # instance for the 52 RSSHub-routed sources to produce anything.
    rsshub_base_url: str = "https://rsshub.app"
    max_items_per_fetch: int = 100
    # SEC requires a self-identifying UA with a contact address; the generic bot
    # UA gets "Your Request Originates from an Undeclared Automated Tool".
    sec_user_agent: str = "MichelleDataHub/0.1 (contact: datahub@polarisagi.com)"

    # Calendar sources are forward-looking: a日历 page must answer "what is
    # coming", so calendar providers are queried over [today-lookback,
    # today+lookahead]. FMP truncates a calendar response at 4,000 rows in date
    # DESC order, which silently drops the near dates — so the window is
    # requested in chunks and merged.
    calendar_lookback_days: int = 7
    calendar_lookahead_days: int = 28
    calendar_window_chunk_days: int = 7
    # Calendars carry far more rows per fetch than a feed (global earnings alone
    # run ~4k/month), so they get their own cap instead of max_items_per_fetch.
    # It is deliberately above the volume of a full window: a *sampled* schedule
    # is worse than none — the one company a user looks up is the one missing.
    # The cap is split evenly across the windows so the retro week cannot eat it.
    calendar_max_items: int = 20_000

    # Scheduling — "实时/高频" sources are polled on this interval (seconds).
    realtime_interval_seconds: int = 120
    # Cap the smallest allowed interval to avoid hammering sources.
    min_interval_seconds: int = 60
    # Global refresh: re-fetch every enabled source on this cadence (hours),
    # independent of each source's 频率. Dedup keeps repeated fetches idempotent.
    # Set to 0 to disable the global refresh job.
    refresh_all_hours: int = 4
    # Directory where each refresh writes its stats report (markdown, one file
    # per run). Empty string disables report writing.
    report_dir: str = "reports"

    # Full-text enrichment: fetch each stored item's URL and extract the article
    # body into content_item.fulltext (null = not attempted, "" = failed).
    fulltext_enabled: bool = True
    fulltext_interval_minutes: int = 15   # scheduler cadence for the enrich job
    fulltext_batch_size: int = 200        # items per enrich run
    # Concurrent article fetches. Extraction is CPU-heavy: on a small host this
    # is what starves the API container (measured 2026-08-05 — /health, which
    # touches no database, took 1.4-6.7s while the enrich job was running).
    fulltext_workers: int = 4
    fulltext_max_chars: int = 200_000     # truncate extracted text beyond this
    # Article pages are fetched with a browser UA (publishers block obvious bots;
    # WSJ-class sites only return og:image with this one). Feeds keep `user_agent`
    # on purpose — Reddit rate-limits browser UAs harder than bot UAs.
    enrich_user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )

    # Retention: delete content_item / fetch_run rows older than this many days
    # (by fetched_at / started_at). 0 disables purging.
    retention_days: int = 7
    # An item whose source-declared published_at is further in the future than
    # this is treated as a dirty timestamp (see runner._sanitize_published).
    # calendar/events are exempt — future dates are the point there.
    max_future_skew_hours: int = 6

    # Media URL templates (empty string disables the field).
    # Source favicon, exposed as DataSourceOut.icon_url / avatar_url; swap for a
    # domestic or self-hosted service if consumers can't reach Google.
    favicon_service_url: str = "https://www.google.com/s2/favicons?domain={domain}&sz=64"
    # Company logo by ticker, injected as payload.logo_url on company items that
    # carry a symbol (FMP's image CDN is public — no API key required).
    stock_logo_service_url: str = "https://images.financialmodelingprep.com/symbol/{symbol}.png"

    # REST API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Optional external provider credentials (only needed for paid/API sources).
    fmp_api_key: str | None = None
    fred_api_key: str | None = None
    finnhub_api_key: str | None = None
    twitterapi_io_key: str | None = None
    acled_api_key: str | None = None
    # Keys held for future providers (no registry source uses them yet).
    alpha_vantage_api_key: str | None = None
    massive_api_key: str | None = None      # Massive (formerly Polygon.io)
    newsapi_org_key: str | None = None      # newsapi.org (≠ newsapi.ai)
    tushare_token: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
