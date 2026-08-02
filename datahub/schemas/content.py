"""Per-module content standards (requirement 1).

`BaseContentItem` is the common shape every module emits. Each module then
declares a payload model describing its module-specific fields (mirroring the
`payload_fields` in module_spec). Fetchers populate `payload` and the matching
schema validates/serializes it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..catalog.module_spec import ModuleKey
from ..config import get_settings


class BaseContentItem(BaseModel):
    """Common normalized fields shared by all modules."""

    external_id: str
    title: str | None = None
    url: str | None = None
    summary: str | None = None
    published_at: datetime | None = None
    payload: dict = Field(default_factory=dict)


# ---- Module-specific payload standards -------------------------------------

class NewsPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    region: str | None = None
    topic: str | None = None
    lang: str | None = None


class EventPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    event_type: str | None = None
    actors: list[str] | None = None
    location: str | None = None
    cameo_code: str | None = None


class CalendarPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    event_date: str | None = None
    calendar_type: str | None = None
    symbol: str | None = None


class CompanyPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    symbol: str | None = None
    exchange: str | None = None
    data_type: str | None = None
    logo_url: str | None = None   # injected from symbol at read time


class MarketPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    instrument: str | None = None
    asset_class: str | None = None
    venue: str | None = None


class MacroPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    country: str | None = None
    indicator: str | None = None
    period: str | None = None


class OpinionPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    platform: str | None = None
    topic: str | None = None
    rank: int | None = None


class ChannelPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    medium: str | None = None
    topic: str | None = None
    lang: str | None = None
    audio_url: str | None = None  # podcast enclosure (+ audio_mime/audio_duration)
    video_url: str | None = None  # video enclosure / YouTube watch URL (+ video_id)


class PersonPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    person: str | None = None
    platform: str | None = None
    bio: str | None = None


CONTENT_SCHEMAS: dict[ModuleKey, type[BaseModel]] = {
    ModuleKey.NEWS: NewsPayload,
    ModuleKey.EVENTS: EventPayload,
    ModuleKey.CALENDAR: CalendarPayload,
    ModuleKey.COMPANY: CompanyPayload,
    ModuleKey.MARKET: MarketPayload,
    ModuleKey.MACRO: MacroPayload,
    ModuleKey.OPINION: OpinionPayload,
    ModuleKey.CHANNEL: ChannelPayload,
    ModuleKey.PERSON: PersonPayload,
}


def content_schema_for(module: str) -> type[BaseModel] | None:
    try:
        return CONTENT_SCHEMAS[ModuleKey(module)]
    except (ValueError, KeyError):
        return None


class ContentItemOut(BaseContentItem):
    """API representation of a stored content item."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    source_id: int
    module: str
    image_url: str | None = None  # lead image (feed media/enclosure or og:image)
    fulltext: str | None = None  # extracted article body (null=not tried, ""=failed)
    fetched_at: datetime

    @model_validator(mode="after")
    def _inject_company_logo(self):
        """company items with a ticker get a logo_url derived from it (public
        logo CDN, see stock_logo_service_url) — computed at read time so it
        also covers historical rows."""
        if self.module == "company" and isinstance(self.payload, dict):
            symbol = self.payload.get("symbol")
            template = get_settings().stock_logo_service_url
            if symbol and template and not self.payload.get("logo_url"):
                self.payload = {**self.payload, "logo_url": template.format(symbol=symbol)}
        return self
