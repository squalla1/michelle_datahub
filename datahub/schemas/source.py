"""API schemas for catalog sources, fetch runs, and modules."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
