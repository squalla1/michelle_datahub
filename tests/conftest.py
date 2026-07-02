"""Shared test fixtures.

Redirect the whole test session to a throwaway SQLite file and disable the
embedded scheduler. This runs before any test module imports `datahub.storage`,
so the engine is built against the temp DB."""

from __future__ import annotations

import os
import tempfile

_TEST_DB = os.path.join(tempfile.gettempdir(), "datahub_pytest.db")
if os.path.exists(_TEST_DB):
    os.remove(_TEST_DB)
os.environ["DATAHUB_DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ["DATAHUB_API_SCHEDULER"] = "0"

import pytest  # noqa: E402

from datahub.models import Base  # noqa: E402
from datahub.storage import engine  # noqa: E402


@pytest.fixture
def clean_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
