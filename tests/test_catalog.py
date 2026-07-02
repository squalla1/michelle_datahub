from pathlib import Path

import pytest

from datahub.catalog import MODULES, load_catalog
from datahub.fetchers.registry import resolve_fetcher

CATALOG = Path(__file__).resolve().parents[1] / "doc" / "Michelle_Datasource_2026-06-02.xlsx"

pytestmark = pytest.mark.skipif(not CATALOG.exists(), reason="registry workbook not present")


def test_loads_all_modules():
    rows = load_catalog(CATALOG)
    assert len(rows) > 500
    modules = {r.module for r in rows}
    assert modules == {m.key.value for m in MODULES}


def test_rows_have_core_fields():
    rows = load_catalog(CATALOG)
    sample = rows[0]
    assert sample.name
    assert sample.module
    # every row should carry its source method
    assert sum(1 for r in rows if r.method) > len(rows) * 0.9


def test_every_method_resolves_or_is_known_unroutable():
    rows = load_catalog(CATALOG)
    methods = {r.method for r in rows if r.method}
    unresolved = {m for m in methods if resolve_fetcher(m) is None}
    # The vast majority must route to a fetcher.
    assert len(unresolved) <= len(methods) * 0.1, unresolved
