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
    catalog_path: str = "doc/Michelle_Datasource_2026-06-02.xlsx"

    # Fetching
    request_timeout: float = 20.0
    user_agent: str = (
        "Mozilla/5.0 (compatible; MichelleDataHub/0.1; +https://example.com/bot)"
    )
    rsshub_base_url: str = "https://rsshub.app"
    max_items_per_fetch: int = 100

    # Scheduling — "实时/高频" sources are polled on this interval (seconds).
    realtime_interval_seconds: int = 120
    # Cap the smallest allowed interval to avoid hammering sources.
    min_interval_seconds: int = 60
    # Global refresh: re-fetch every enabled source on this cadence (hours),
    # independent of each source's 频率. Dedup keeps repeated fetches idempotent.
    # Set to 0 to disable the global refresh job.
    refresh_all_hours: int = 2

    # REST API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Optional external provider credentials (only needed for paid/API sources).
    fmp_api_key: str | None = None
    fred_api_key: str | None = None
    twitterapi_io_key: str | None = None
    acled_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
