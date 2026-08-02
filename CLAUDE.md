# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A catalog-driven backend that periodically ingests content from the data sources
defined in `data/Michelle_Datasource_2026-06-02.xlsx` and serves it over REST.
The Excel workbook is the **source registry**, not just documentation: each of its
9 tabs is a *module*, each row is a *data source* declaring how it is fetched
(`方式` column) and how often (`频率` column). The system parses that registry into
a database, schedules one fetch job per source by frequency, routes each fetch to a
fetcher by method, and exposes the results via FastAPI.

Language is Python (chosen because the registry is ~60% RSS/Atom + HTML scraping +
Python-native data APIs like AKShare/GDELT/ArXiv).

## Commands

```bash
# Setup (run from this directory)
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Pipeline
datahub init-db                       # create tables
datahub ingest [--path FILE]          # parse the Excel registry into data_source
datahub list --module news --limit 5  # inspect the catalog
datahub run --source 2                # fetch ONE source now (synchronous)
datahub run --module news --priority P1 --limit 5   # fetch a batch now
datahub refresh [--module news]       # fetch ALL enabled sources once (dedup); manual twin of the 4h job
datahub enrich [--limit N]            # extract article fulltext into content_item.fulltext
datahub purge [--days N]              # delete content older than the retention window (default 7d)
datahub serve                         # REST API + in-process scheduler -> :8000/docs
datahub schedule                      # run the scheduler as a standalone foreground worker

# Tests
pytest -q
pytest tests/test_catalog.py::test_loads_all_modules   # single test
```

`make install|init|ingest|serve|schedule|run|refresh|test` wrap the above.

`tests/test_catalog.py` is auto-skipped if `data/Michelle_Datasource_*.xlsx` is
absent; `tests/test_frequency.py` is pure-unit and always runs.

## Architecture

Data flows in one direction; trace a change along it:

```
Excel registry → catalog (parse + module standards) → data_source table
   → scheduler (频率 → interval/cron trigger) → fetchers (方式 → fetcher)
   → ingest.runner (dedup + store) → content_item / fetch_run → FastAPI
```

Package responsibilities (`datahub/`):

- `catalog/` — `excel_loader.py` parses the workbook (row 1 = title, row 2 =
  header, row 3+ = data; columns mapped by Chinese header label, not position).
  `module_spec.py` is the source of truth for the 9 modules.
- `models/` — SQLAlchemy 2.0 ORM: `DataSource` (a registry row), `FetchRun` (one
  execution audit), `ContentItem` (a fetched item; common fields normalized,
  module-specific fields in the JSON `payload`).
- `schemas/` — Pydantic. `content.py` defines the per-module payload standards;
  `source.py` the API DTOs.
- `fetchers/` — one `Fetcher` subclass per `方式` family. `registry.py` resolves a
  source's method string to a fetcher by substring keyword match.
- `scheduler/` — `frequency.py` maps the Chinese `频率` to a `TriggerSpec`;
  `service.py` builds an APScheduler job per schedulable source, plus one global
  `refresh-all` cron job (every `refresh_all_hours`, default 4h) that re-fetches
  every enabled source via `ingest.runner.run_all_sources` (dedup makes it idempotent).
  Every `run_all_sources` sweep writes a per-run stats report (markdown) to
  `reports/refresh/` (`DATAHUB_REPORT_DIR`; empty disables; gitignored).
  Two more built-in jobs: `fulltext-enrich` (every `fulltext_interval_minutes`,
  extracts article bodies via trafilatura into `content_item.fulltext` — null=not
  tried, ""=failed, never retried — and backfills `image_url` from the page's
  og:image when the feed carried none) and `retention-purge` (daily 04:30 UTC,
  deletes content/runs older than `retention_days`, default 7).
- `ingest/` — `catalog_ingest.py` (idempotent upsert of the registry),
  `runner.py` (`run_source` = fetch + dedup-store + record a FetchRun).
- `api/` — `app.py` factory + `routes/`. `routes/content.py` serves both a generic
  cross-module query (`GET /api/v1/content`) and a per-type feed
  (`GET /api/v1/content/{module}`) that defaults to *today's* items (UTC) and returns
  the latest N; `?by=published|fetched` chooses the date field; when `date` is
  omitted and today is empty it falls back to the latest N overall (low-frequency
  modules). `storage/` — engine,
  session, `init_db`. Full endpoint reference is `docs/API_REFERENCE.md` (or the live
  `/docs`); Chinese versions are the `docs/*.zh-CN.md` twins — update both when
  endpoints change.
- `cli.py` — argparse entrypoint (the `datahub` console script).

## Key conventions

- **The two driver columns.** `方式` decides the fetcher (`fetchers/registry.py`);
  `频率` decides the schedule (`scheduler/frequency.py`). When the registry gains a
  new method or cadence string, extend those two files — nothing else needs to know.
- **Adding a fetcher:** subclass `Fetcher`, set `method_keywords`, implement
  `fetch(source) -> FetchResult`, and register it in `fetchers/registry.py`
  `_fetchers()`. Order matters there — specific fetchers (RSSHub, Email) precede the
  broad `RssFetcher` fallback. Fetchers must NOT raise on expected failure; return
  `FetchResult(status="error"|"skipped", note=...)` so the run is recorded.
- **Adding an API provider** (paid/keyed source): add a `ProviderFn` to
  `fetchers/api.py` `PROVIDERS`, keyed by a lowercase substring of the `方式` value.
  Use `_needs_key(...)` to gracefully skip until the credential is set. GDELT and
  ArXiv are the key-free reference implementations; FMP (registry-row → /stable
  endpoint routing), FRED (series from URL/账号 column), and Finnhub are the keyed
  ones (keys in `.env`, see `docs/ops/数据源Key接入_2026-08-02.md`).
- **Module definitions are centralized** in `catalog/module_spec.py` and mirrored by
  `schemas/content.py` `CONTENT_SCHEMAS`. Change both together when adding/altering a
  module so the standard and its validator stay in sync.
- **Dedup** is `(source_id, external_id)`; RSS uses entry id/guid/link, others hash.
  Catalog upsert keys on `(module, name, url)` and also de-dups exact repeats within
  a single workbook (the spreadsheet contains some).
- **Config** is `datahub/config.py` (`Settings`), all overridable via `DATAHUB_*`
  env vars or a `.env`; never read env directly elsewhere — go through `get_settings()`.
  `DATAHUB_API_SCHEDULER=0` runs `serve` without the embedded scheduler (use a
  separate `datahub schedule` worker).
- **Frequency semantics:** `实时/高频` → interval poll (capped by
  `min_interval_seconds`); `N分钟` (incl. ranges like `10-15分钟`) → takes the lower
  bound; `每日/周/月/季/年` → cron; `不定期/偶尔/按provider`/blank → manual (on-demand
  only, never auto-scheduled).
- SQLAlchemy 2.0 typed-`Mapped` style throughout; use `session_scope()` for
  transactional writes and the `get_session` FastAPI dependency for reads.
- **Datetimes are naive UTC everywhere.** Columns are `TIMESTAMP WITHOUT TIME
  ZONE`; an *aware* datetime gets cast through the PG session timezone on write
  (RDS defaulted to Asia/Tokyo — this shifted the whole DB by +9h once, migrated
  2026-07-08). Use `models.utcnow()` / `models.to_naive_utc()`; never
  `datetime.now(timezone.utc)` directly in write paths. The engine also forces
  `-c timezone=utc` and the database default is `UTC` as belt-and-suspenders.
- **Database** is SQLite by default, PostgreSQL in production (`DATAHUB_DATABASE_URL`
  must use the `postgresql+psycopg://` driver, from the `[postgres]` extra). JSON
  columns are `JSON().with_variant(JSONB, "postgresql")` — keep `deploy/schema.sql`
  byte-compatible with `models/` when changing a column (it's the canonical DDL and
  must match `create_all`). Deployment (Docker/compose/systemd) is in `docs/DEPLOY.md`.
