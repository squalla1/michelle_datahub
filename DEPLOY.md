# Deployment Guide

Packaging and deployment for **Michelle DataHub** (catalog-driven ingestion + REST
API) on **PostgreSQL**.

The system is two long-running processes plus one-shot setup steps:

| Process | Command | Role |
|---|---|---|
| API | `datahub serve` | FastAPI on `:8000` (`/docs`, `/api/v1/...`) |
| Scheduler | `datahub schedule` | per-source `频率` jobs + global 2-hour refresh |
| Setup (once) | `datahub init-db && datahub ingest` | create schema + load the Excel registry |

In small deployments one process can do both (run `serve` with the embedded
scheduler). For anything real, run the API and the scheduler **separately** so API
restarts don't interrupt fetching — set `DATAHUB_API_SCHEDULER=0` on the API.

---

## 1. Prerequisites

- Python 3.10+ (image uses 3.12) and PostgreSQL 14+.
- The Excel registry file (`doc/Michelle_Datasource_*.xlsx`) reachable at
  `DATAHUB_CATALOG_PATH`.

## 2. Configuration

All settings come from `DATAHUB_*` env vars (or a `.env`); see `.env.example`.
The deployment-critical ones:

| Variable | Example | Notes |
|---|---|---|
| `DATAHUB_DATABASE_URL` | `postgresql+psycopg://datahub:pw@db:5432/datahub` | **must** use the `+psycopg` (psycopg 3) driver |
| `DATAHUB_CATALOG_PATH` | `/data/Michelle_Datasource_2026-06-02.xlsx` | path to the registry |
| `DATAHUB_API_SCHEDULER` | `0` on the API process | `0` = don't embed the scheduler |
| `DATAHUB_REFRESH_ALL_HOURS` | `2` | global refresh cadence; `0` disables |
| `DATAHUB_RSSHUB_BASE_URL` | `https://your-rsshub` | self-host RSSHub; the public instance is unreliable |
| `DATAHUB_*_API_KEY` | — | optional provider credentials (FMP/FRED/twitterapi.io/ACLED) |

## 3. Database setup (PostgreSQL)

Create the database/role, then create the schema **one** of two equivalent ways:

```bash
# Role + database
createdb datahub && createuser datahub --pwprompt   # or via your managed PG

# (a) DBA-managed — apply the canonical DDL
psql "$DATAHUB_DATABASE_URL" -f deploy/schema.sql

# (b) App-managed — let SQLAlchemy create_all build it
datahub init-db
```

Both produce the **same** schema (`deploy/schema.sql` is kept byte-compatible with
the ORM in `datahub/models/`: `SERIAL` PKs, `JSONB` payloads, `TIMESTAMP` UTC,
`uq_source(module,name,url)` / `uq_content(source_id,external_id)` dedup keys, and
the supporting indexes). See [`deploy/schema.sql`](deploy/schema.sql) for the
authoritative definition. Then load the registry:

```bash
datahub ingest        # parse the Excel workbook into data_source (idempotent)
```

### Schema overview

```
data_source ──1:N──> fetch_run     (audit of each fetch execution)
     │
     └────────1:N──> content_item  (fetched items; dedup on source_id+external_id)
```

`content_item.payload` and `data_source.extra` are `JSONB`. Timestamps are UTC.
The per-type API (`GET /api/v1/content/{module}`) filters on `published_at` /
`fetched_at` — both indexed.

## 4. Deploy with Docker Compose (recommended)

Artifacts live in `deploy/` (`Dockerfile`, `docker-compose.yml`).

```bash
cd deploy
export POSTGRES_PASSWORD=change-me

docker compose up -d db                 # 1. PostgreSQL (with healthcheck)
docker compose run --rm ingest          # 2. create schema + load the registry (once)
docker compose up -d api scheduler      # 3. API on :8000 + scheduler worker
```

The compose file mounts the project's `doc/` read-only into `/data` for the registry, puts
Postgres data on the `pgdata` volume, runs the API with the scheduler disabled, and
runs a dedicated `scheduler` service that owns the 2-hour refresh. Reload the
registry later without downtime:

```bash
docker compose run --rm ingest
curl -X POST localhost:8000/api/v1/jobs/reload    # rebuild scheduler jobs
```

## 5. Deploy without Docker (systemd)

```bash
python -m venv /opt/datahub/.venv
/opt/datahub/.venv/bin/pip install ".[postgres]"
```

Two units sharing one `EnvironmentFile=/opt/datahub/.env`:

```ini
# /etc/systemd/system/datahub-api.service
[Service]
EnvironmentFile=/opt/datahub/.env
Environment=DATAHUB_API_SCHEDULER=0
ExecStart=/opt/datahub/.venv/bin/datahub serve
Restart=always

# /etc/systemd/system/datahub-scheduler.service
[Service]
EnvironmentFile=/opt/datahub/.env
ExecStart=/opt/datahub/.venv/bin/datahub schedule
Restart=always
```

For multiple API replicas behind a load balancer, keep exactly **one** scheduler
process (it's a singleton writer); APScheduler here is in-memory per process, so
running several schedulers would duplicate fetches (dedup makes that harmless but
wasteful).

## 6. Verify

```bash
curl localhost:8000/health
curl localhost:8000/api/v1/modules                 # 9 types + source counts
curl "localhost:8000/api/v1/content/news?limit=5"  # latest 5 news today
curl localhost:8000/api/v1/jobs                     # scheduler state (incl. refresh-all)
datahub refresh --module news                       # force a fetch now (dedup)
```

## 7. Operations

- **Backups:** `pg_dump`. Content is reproducible by re-fetching, but `fetch_run`
  history and dedup state are not.
- **Growth:** `content_item` is the hot table. If it gets large, partition by
  `fetched_at` (month) and/or add `ix_content_module_published` (commented in
  `schema.sql`). PKs are `SERIAL` (int32) — switch to `BIGINT IDENTITY` before
  approaching ~2.1B rows.
- **Monitoring:** poll `GET /api/v1/jobs`; alert on `fetch_run.status='error'`
  rates. ~30% of live sources fail transiently (404/403/SSL/rate-limit) — track the
  trend, not individual failures.
- **Driver note:** the URL scheme must be `postgresql+psycopg://` (psycopg 3, from
  the `[postgres]` extra), **not** `postgresql://` (which defaults to psycopg2).
```
