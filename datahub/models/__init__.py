"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# JSON everywhere, but JSONB on PostgreSQL (indexable, more compact). SQLite and
# other backends keep plain JSON.
JSONType = JSON().with_variant(JSONB, "postgresql")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class DataSource(Base):
    """One row of the Excel registry, normalized."""

    __tablename__ = "data_source"
    __table_args__ = (UniqueConstraint("module", "name", "url", name="uq_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module: Mapped[str] = mapped_column(String(32), index=True)
    tab: Mapped[str] = mapped_column(String(64))
    l1_category: Mapped[str | None] = mapped_column(String(128))
    l2_category: Mapped[str | None] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(256), index=True)
    url: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str | None] = mapped_column(String(64), index=True)
    paid: Mapped[str | None] = mapped_column(String(64))
    account: Mapped[str | None] = mapped_column(String(128))
    frequency: Mapped[str | None] = mapped_column(String(64))
    remark: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str | None] = mapped_column(String(8), index=True)
    health: Mapped[str | None] = mapped_column(String(8))
    extra: Mapped[dict] = mapped_column(JSONType, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    runs: Mapped[list["FetchRun"]] = relationship(back_populates="source")


class FetchRun(Base):
    """Audit record for one fetch execution against a source."""

    __tablename__ = "fetch_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="running")  # ok/error/skipped
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)

    source: Mapped["DataSource"] = relationship(back_populates="runs")


class ContentItem(Base):
    """A fetched content item. Common fields are normalized; module-specific
    fields live in `payload` (shaped per the module's schema)."""

    __tablename__ = "content_item"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_content"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source.id"), index=True)
    module: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str] = mapped_column(String(512))
    title: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    # Extracted article body: null = not attempted yet, "" = attempted but failed.
    fulltext: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
