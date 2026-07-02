"""FastAPI dependencies."""

from __future__ import annotations

from typing import Iterator

from ..storage import SessionLocal


def get_session() -> Iterator:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
