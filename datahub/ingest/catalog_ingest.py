"""Load the Excel registry into the data_source table (idempotent upsert)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from ..catalog import load_catalog
from ..config import get_settings
from ..models import DataSource
from ..storage import session_scope


def ingest_catalog(path: str | Path | None = None) -> dict:
    """Parse the workbook and upsert each row keyed on (module, name, url).

    Returns a summary dict: {created, updated, total}."""
    path = path or get_settings().catalog_path
    rows = load_catalog(path)
    created = updated = skipped = 0
    seen: set[tuple] = set()

    with session_scope() as session:
        for row in rows:
            key = (row.module, row.name, row.url)
            if key in seen:
                skipped += 1  # exact duplicate within the workbook
                continue
            seen.add(key)
            existing = session.scalar(
                select(DataSource).where(
                    DataSource.module == row.module,
                    DataSource.name == row.name,
                    DataSource.url == row.url,
                )
            )
            if existing is None:
                session.add(
                    DataSource(
                        module=row.module,
                        tab=row.tab,
                        l1_category=row.l1_category,
                        l2_category=row.l2_category,
                        name=row.name,
                        url=row.url,
                        method=row.method,
                        paid=row.paid,
                        account=row.account,
                        frequency=row.frequency,
                        remark=row.remark,
                        priority=row.priority,
                        health=row.health,
                        extra=row.extra,
                    )
                )
                created += 1
            else:
                existing.l1_category = row.l1_category
                existing.l2_category = row.l2_category
                existing.method = row.method
                existing.paid = row.paid
                existing.account = row.account
                existing.frequency = row.frequency
                existing.remark = row.remark
                existing.priority = row.priority
                existing.health = row.health
                existing.extra = row.extra
                updated += 1

    return {"created": created, "updated": updated, "skipped": skipped, "total": len(rows)}
