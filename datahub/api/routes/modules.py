"""Module-standard introspection endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...catalog import MODULES
from ...models import DataSource
from ...schemas import ModuleOut
from ..deps import get_session

router = APIRouter(prefix="/api/v1/modules", tags=["modules"])


@router.get("", response_model=list[ModuleOut])
def list_modules(session: Session = Depends(get_session)) -> list[ModuleOut]:
    counts = dict(
        session.execute(
            select(DataSource.module, func.count()).group_by(DataSource.module)
        ).all()
    )
    return [
        ModuleOut(
            key=m.key.value,
            tab=m.tab,
            display_name=m.display_name,
            item_title=m.item_title,
            payload_fields=list(m.payload_fields),
            note=m.note,
            source_count=counts.get(m.key.value, 0),
        )
        for m in MODULES
    ]
