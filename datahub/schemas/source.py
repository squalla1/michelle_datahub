"""API schemas for catalog sources, fetch runs, and modules."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, model_validator

from ..config import get_settings


class DataSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    module: str
    tab: str
    l1_category: str | None
    l2_category: str | None
    name: str
    url: str | None
    method: str | None
    paid: str | None
    frequency: str | None
    priority: str | None
    health: str | None
    enabled: bool
    # Derived 64px favicon of the source's domain (see favicon_service_url).
    # avatar_url currently mirrors icon_url; it upgrades to a real channel/person
    # avatar once a per-platform source becomes available.
    icon_url: str | None = None
    avatar_url: str | None = None

    @model_validator(mode="after")
    def _derive_icons(self):
        if self.icon_url is None and self.url and self.url.startswith("http"):
            domain = urlparse(self.url).netloc
            template = get_settings().favicon_service_url
            if domain and template:
                self.icon_url = template.format(domain=domain)
        if self.avatar_url is None:
            self.avatar_url = self.icon_url
        return self


class FetchRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source_id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    item_count: int
    new_count: int
    error: str | None


class ModuleOut(BaseModel):
    key: str
    tab: str
    display_name: str
    item_title: str
    payload_fields: list[str]
    note: str
    source_count: int | None = None
