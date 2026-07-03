# API Reference — Michelle DataHub

> **Language:** English | [中文](API_REFERENCE.zh-CN.md)

REST API for the catalog-driven ingestion engine. All content is fetched from the
data-source registry, stored in the database, refreshed every 2 hours (dedup), and
served read-only through the endpoints below.

- **Base URL:** `http://<host>:8000` (default port `8000`)
- **Prefix:** every data endpoint is under `/api/v1`
- **Format:** JSON; all timestamps are **UTC** (ISO 8601)
- **Auth:** none (deploy behind a gateway/reverse proxy if exposure matters)
- **Live/interactive docs:** `GET /docs` (Swagger UI), `GET /redoc`, `GET /openapi.json`
  — auto-generated from the code and always authoritative.

Source of truth: routes in `datahub/api/routes/`, response models in
`datahub/schemas/`.

---

## Modules (content types)

Content is organized into **9 module types**. Every `{module}` path parameter and
`module` query filter uses one of these keys:

| key | 中文 | item represents |
|---|---|---|
| `news` | 新闻 | a news headline |
| `events` | 全球事件 | a global event |
| `calendar` | 日历 | a scheduled date/item (earnings, IR, econ…) |
| `company` | 公司 | a company profile/financial/filing item |
| `market` | 市场 | a tradable instrument datum |
| `macro` | 宏观 | a macro indicator release |
| `opinion` | 关键舆论平台 | an opinion-platform entry |
| `channel` | 关键频道 | a channel entry (podcast/blog/YouTube…) |
| `person` | 关键人物 | a key-person update |

---

## Endpoint index

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness + configured catalog path |
| GET | `/api/v1/modules` | list the 9 module standards + source counts |
| GET | `/api/v1/content` | generic cross-module content query |
| GET | `/api/v1/content/{module}` | per-type feed: today's latest N |
| GET | `/api/v1/sources` | list catalog sources (registry rows) |
| GET | `/api/v1/sources/{id}` | one source by id |
| POST | `/api/v1/sources/{id}/fetch` | trigger an immediate synchronous fetch |
| GET | `/api/v1/sources/{id}/runs` | recent fetch-run audit records for a source |
| GET | `/api/v1/jobs` | scheduler status + jobs |
| POST | `/api/v1/jobs/reload` | rebuild scheduler jobs from the catalog |
| POST | `/api/v1/jobs/catalog/reload` | re-parse the Excel registry, then rebuild jobs |

---

## Health

### `GET /health`

Liveness probe.

**200** →
```json
{ "status": "ok", "catalog_path": "data/Michelle_Datasource_2026-06-02.xlsx" }
```

---

## Modules

### `GET /api/v1/modules`

Returns the standard for each of the 9 modules plus how many sources it has.

**Response:** `ModuleOut[]`

| field | type | description |
|---|---|---|
| `key` | string | module key (see table above) |
| `tab` | string | Excel tab name |
| `display_name` | string | human-readable name |
| `item_title` | string | what a content item's `title` means for this module |
| `payload_fields` | string[] | module-specific fields present in `payload` |
| `note` | string | short description |
| `source_count` | int \| null | number of catalog sources in this module |

**Example**
```bash
curl localhost:8000/api/v1/modules
```

---

## Content

The primary data API. Items share a common shape (`ContentItemOut`); module-specific
fields live inside `payload`.

### `ContentItemOut`

| field | type | description |
|---|---|---|
| `id` | int | item id |
| `source_id` | int | owning source (→ `/api/v1/sources/{id}`) |
| `module` | string | module key |
| `external_id` | string | source-native id (dedup key with `source_id`) |
| `title` | string \| null | headline / item title |
| `url` | string \| null | link to the item |
| `summary` | string \| null | short text/summary |
| `published_at` | datetime \| null | when the source published it (UTC) |
| `fetched_at` | datetime | when we ingested it (UTC) |
| `payload` | object | module-specific fields (see per-module standards below) |

### `GET /api/v1/content/{module}` — per-type feed (recommended)

Latest **N** items of one module type for a given day. Defaults to **today (UTC)**.

| param | in | type | default | description |
|---|---|---|---|---|
| `module` | path | string | — | one of the 9 module keys; unknown → **404** |
| `date` | query | date (`YYYY-MM-DD`) | today (UTC) | calendar day to return |
| `by` | query | `published` \| `fetched` | `published` | which timestamp `date` filters and ordering uses |
| `q` | query | string | — | case-insensitive substring match on `title` |
| `limit` | query | int (1–500) | 50 | return the latest N |
| `offset` | query | int | 0 | pagination offset |

Ordering is newest-first on the chosen `by` field. Note: with `by=published`, items
without a publish timestamp (e.g. scraped links) are excluded — use `by=fetched` to
include everything ingested that day.

**Examples**
```bash
# today's latest 20 news
curl "localhost:8000/api/v1/content/news?limit=20"
# a specific past day
curl "localhost:8000/api/v1/content/market?date=2026-06-21"
# everything ingested today, regardless of publish date
curl "localhost:8000/api/v1/content/person?by=fetched"
# title search within today's events
curl "localhost:8000/api/v1/content/events?q=oil"
```

**Response:** `ContentItemOut[]`
```json
[
  {
    "id": 1024,
    "source_id": 2,
    "module": "news",
    "external_id": "https://example.com/a1",
    "title": "Example headline",
    "url": "https://example.com/a1",
    "summary": "…",
    "published_at": "2026-07-02T08:15:00",
    "fetched_at": "2026-07-02T08:20:11",
    "payload": { "author": "…" }
  }
]
```

### `GET /api/v1/content` — generic query

Cross-module query with no date default (returns latest across all dates unless
filtered). Use this for search/pagination across types.

| param | in | type | default | description |
|---|---|---|---|---|
| `module` | query | string | — | filter by module key |
| `source_id` | query | int | — | filter by owning source |
| `date` | query | date | — | calendar day (UTC); no default |
| `by` | query | `published` \| `fetched` | `published` | date field for the `date` filter |
| `since` | query | datetime | — | `published_at >= since` |
| `q` | query | string | — | substring match on `title` |
| `limit` | query | int (1–500) | 50 | page size |
| `offset` | query | int | 0 | pagination offset |

Ordering is by `fetched_at` descending.

**Response:** `ContentItemOut[]`

### Per-module `payload` standards

Every module allows extra keys (`extra="allow"`), but these are the declared fields:

| module | `payload` fields |
|---|---|
| `news` | `region`, `topic`, `lang` |
| `events` | `event_type`, `actors` (string[]), `location`, `cameo_code` |
| `calendar` | `event_date`, `calendar_type`, `symbol` |
| `company` | `symbol`, `exchange`, `data_type` |
| `market` | `instrument`, `asset_class`, `venue` |
| `macro` | `country`, `indicator`, `period` |
| `opinion` | `platform`, `topic`, `rank` (int) |
| `channel` | `medium`, `topic`, `lang` |
| `person` | `person`, `platform`, `bio` |

---

## Sources (catalog)

The registry rows — the data sources themselves, not their content.

### `DataSourceOut`

| field | type | description |
|---|---|---|
| `id` | int | source id |
| `module` | string | module key |
| `tab` | string | Excel tab |
| `l1_category` / `l2_category` | string \| null | registry categories |
| `name` | string | source name |
| `url` | string \| null | source URL |
| `method` | string \| null | `方式` — how it's fetched |
| `paid` | string \| null | paid/free marker |
| `frequency` | string \| null | `频率` — how often |
| `priority` | string \| null | e.g. `P1` |
| `health` | string \| null | health marker |
| `enabled` | bool | whether it is scheduled/fetched |

### `GET /api/v1/sources`

| param | type | default | description |
|---|---|---|---|
| `module` | string | — | exact module key |
| `priority` | string | — | exact priority (e.g. `P1`) |
| `method` | string | — | substring match on `方式` |
| `enabled` | bool | — | filter by enabled flag |
| `q` | string | — | substring match on `name` |
| `limit` | int (≤1000) | 100 | page size |
| `offset` | int | 0 | pagination offset |

**Response:** `DataSourceOut[]` (ordered by id)

### `GET /api/v1/sources/{id}`

One source. **404** if not found. **Response:** `DataSourceOut`

### `POST /api/v1/sources/{id}/fetch`

Trigger an **immediate synchronous** fetch of one source (fetch + dedup-store +
record a run). **404** if the source doesn't exist.

**Response** (summary):
```json
{
  "source_id": 2, "name": "South China Morning Post", "module": "news",
  "status": "ok", "fetched": 50, "new": 12, "note": null
}
```
`status` ∈ `ok` / `error` / `skipped`. `fetched` = items returned; `new` = newly
stored after dedup.

### `GET /api/v1/sources/{id}/runs`

Recent fetch-run audit records, newest first.

| param | type | default | description |
|---|---|---|---|
| `limit` | int (≤200) | 20 | number of runs |

**Response:** `FetchRunOut[]`

| field | type | description |
|---|---|---|
| `id` | int | run id |
| `source_id` | int | source |
| `started_at` | datetime | run start (UTC) |
| `finished_at` | datetime \| null | run end (UTC) |
| `status` | string | `ok` / `error` / `skipped` / `running` |
| `item_count` | int | items returned by the fetch |
| `new_count` | int | items newly stored (after dedup) |
| `error` | string \| null | error/skip note if any |

---

## Jobs (scheduler control)

> These endpoints operate on the **embedded scheduler of the API process**. In a
> split deployment (`DATAHUB_API_SCHEDULER=0` + separate `datahub schedule`
> worker) they report `running: false` / affect nothing — manage the worker
> process directly instead (restart it to reload jobs).

### `GET /api/v1/jobs`

Scheduler status and the current job table (per-source `频率` jobs + the global
`refresh-all` job that runs every 2 hours).

```json
{
  "running": true,
  "jobs": [
    { "id": "refresh-all", "next_run_time": "2026-07-02T10:00:00+00:00", "trigger": "cron[hour='*/2', minute='0']" },
    { "id": "src-2", "next_run_time": "…", "trigger": "interval[0:15:00]" }
  ]
}
```

### `POST /api/v1/jobs/reload`

Rebuild the scheduler jobs from the current catalog state (e.g. after enabling/
disabling sources).

```json
{ "reloaded": true, "by_kind": {"interval": 774, "cron": 414, "manual": 44, "refresh": 1}, "total_jobs": 1189 }
```

### `POST /api/v1/jobs/catalog/reload`

Re-parse the Excel registry into the catalog, then rebuild jobs. Use after updating
the workbook.

```json
{ "catalog": {"created": 0, "updated": 3, "skipped": 1, "total": 1233}, "total_jobs": 1189 }
```

---

## Errors

Standard FastAPI error envelope:
```json
{ "detail": "unknown module 'foo'; one of ['calendar', 'channel', 'company', 'events', 'macro', 'market', 'news', 'opinion', 'person']" }
```

| status | when |
|---|---|
| `404` | unknown `{module}` or missing source id |
| `422` | invalid params (e.g. `by` not `published`/`fetched`, bad date, out-of-range `limit`) |

---

## Notes

- Data is populated by the scheduler (every 2h global refresh + per-source cadence)
  and by `POST /api/v1/sources/{id}/fetch`. A freshly initialized DB is empty until
  the first fetch/refresh runs.
- Dedup key is `(source_id, external_id)`, so repeated refreshes only add genuinely
  new items — safe to poll and re-fetch.
- `published_at` is null for sources that carry no timestamp; prefer `by=fetched`
  when you need "what arrived today" rather than "what was published today".
