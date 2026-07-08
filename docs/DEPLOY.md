# Deployment Guide

> **Language:** English | [中文](DEPLOY.zh-CN.md)

The database is a **managed PostgreSQL** (Alibaba Cloud RDS, verified on 18.3) —
nothing self-hosted. Two long-running processes plus a one-shot init:

| Process | Command | Notes |
|---|---|---|
| API | `datahub serve` | REST on `:8000` (set `DATAHUB_API_SCHEDULER=0`) |
| Scheduler | `datahub schedule` | per-source jobs + global 2-hour refresh |
| Init (once) | `datahub init-db && datahub ingest` | create tables + load registry (both idempotent) |

## 1. Configuration

Project-root `.env` (template: `.env.example`). **The database connection is
configured in exactly one place:**

```bash
DATAHUB_DATABASE_URL=postgresql+psycopg://USER:PASS@<rds-host>:5432/<dbname>
```

- The scheme must be `postgresql+psycopg://` (psycopg 3, from
  `pip install ".[postgres]"`); plain `postgresql://` fails.
- The server's outbound IP must be in the RDS whitelist.
- **The database timezone must be UTC**: `ALTER DATABASE <name> SET timezone TO
  'UTC';` (managed PG often defaults to a local zone — Alibaba Japan uses
  Asia/Tokyo — which silently stores local time into TIMESTAMP columns). The
  app also forces UTC at the connection level; this is belt-and-suspenders.

Optional:

| Variable | Default | Purpose |
|---|---|---|
| `DATAHUB_CATALOG_PATH` | `data/….xlsx` | registry path (relative to working dir) |
| `DATAHUB_REPORT_DIR` | `reports` | per-refresh stats reports |
| `DATAHUB_REFRESH_ALL_HOURS` | `2` | global refresh cadence; `0` disables |
| `DATAHUB_RSSHUB_BASE_URL` | public instance (unreliable) | self-hosted RSSHub |
| `DATAHUB_*_API_KEY` | empty | provider keys (twitterapi.io/FMP/FRED/ACLED) |

## 2. Option A: Docker Compose

```bash
cp .env.example .env && vi .env       # set DATAHUB_DATABASE_URL
cd deploy
docker compose run --rm ingest        # once: create tables + load registry
docker compose up -d api scheduler
```

After updating the Excel registry:

```bash
docker compose run --rm ingest && docker compose restart scheduler
```

> `POST /api/v1/jobs/reload` only touches the API process's embedded scheduler —
> in this split deployment it does **not** affect the worker; don't use it.

## 3. Option B: systemd

```bash
git clone <repo> /opt/datahub/app
python -m venv /opt/datahub/.venv
/opt/datahub/.venv/bin/pip install -e "/opt/datahub/app[postgres]"
cp /opt/datahub/app/.env.example /opt/datahub/.env   # edit per §1
```

```ini
# /etc/systemd/system/datahub-api.service
[Unit]
Description=Michelle DataHub API
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/opt/datahub/app
EnvironmentFile=/opt/datahub/.env
Environment=DATAHUB_API_SCHEDULER=0
ExecStart=/opt/datahub/.venv/bin/datahub serve
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/datahub-scheduler.service
[Unit]
Description=Michelle DataHub scheduler
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/opt/datahub/app
EnvironmentFile=/opt/datahub/.env
ExecStart=/opt/datahub/.venv/bin/datahub schedule
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
cd /opt/datahub/app && /opt/datahub/.venv/bin/datahub init-db && /opt/datahub/.venv/bin/datahub ingest
systemctl daemon-reload && systemctl enable --now datahub-api datahub-scheduler
```

Note: `DATAHUB_CATALOG_PATH` and `DATAHUB_REPORT_DIR` default to relative paths
resolved against `WorkingDirectory` — keep it as above, or use absolute paths in
`.env`.

## 4. nginx reverse proxy (HTTPS)

nginx runs on the host; the API container publishes on the host loopback
`127.0.0.1:8000` (compose default). Domain `mai.polarisagi.com`, port 80
redirects to 443:

```bash
cp deploy/nginx.conf /etc/nginx/conf.d/datahub.conf
mkdir -p /etc/nginx/cert && cp polarisagi.com.{pem,key} /etc/nginx/cert/
chmod 600 /etc/nginx/cert/polarisagi.com.key
nginx -t && systemctl reload nginx
```

The config blocks external access to `/api/v1/jobs` (the API has no auth); open
only 80/443 in the security group. The Alibaba Cloud certificate renews manually —
replace the two files and reload when it expires.

## 5. Verify

```bash
curl localhost:8000/health                          # app directly
curl https://mai.polarisagi.com/health              # via nginx (80 should 301 → 443)
curl "https://mai.polarisagi.com/api/v1/content/news?limit=5"
journalctl -u datahub-scheduler | grep "scheduler running"   # or: docker compose logs scheduler
ls reports/refresh/          # one stats report per refresh sweep
```

In the split deployment `GET /api/v1/jobs` returning `running: false` is normal —
it reflects the API process, not the worker.

## 6. Operations

- **Outcomes:** `reports/refresh/*.md` — per-sweep ok/error/skipped + per-module
  new items.
- **Alerting:** `select max(started_at) from fetch_run` must stay within the
  refresh cadence; watch the error-rate trend (~30% transient failures among live
  sources is normal).
- **Storage:** the enrichment job extracts article fulltext every 15 min; retention
  is 7 days (`DATAHUB_RETENTION_DAYS`) with a daily 04:30 UTC purge — table size is
  naturally capped.
- **Backups:** `pg_dump`; content is re-fetchable, `fetch_run` history and dedup
  state are not.
- **DDL reference:** `deploy/schema.sql` is the canonical DDL, identical to what
  `datahub init-db` creates — DBAs can apply it directly with `psql -f`.
