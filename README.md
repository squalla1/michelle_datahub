# Michelle DataHub

A catalog-driven backend that **periodically ingests content from the data
sources defined in `doc/Michelle_Datasource_2026-06-02.xlsx`** and exposes it
over a REST API.

The Excel workbook is treated as a *source registry*: each of its 9 tabs is a
**module**, and each row is a **data source** that declares how it is fetched
(`方式`) and how often (`频率`). DataHub parses that registry, schedules a fetch
job per source according to its frequency, normalizes results into a per-module
content standard, and serves everything via HTTP.

## Why Python

The registry is dominated by RSS/Atom feeds (~60%), HTML scraping, and
Python-native data APIs (AKShare, GDELT, ArXiv). Python's `feedparser`,
`httpx`, `BeautifulSoup`, FastAPI, APScheduler and SQLAlchemy make the ingestion
+ scheduling + API stack far lighter than the Java equivalent.

## Architecture

```
Excel registry ──> catalog (parse + module standards)
                        │
                        ▼
                   data_source table
                        │
        scheduler (频率 → interval/cron)   ── on-demand fetch ──┐
                        │                                       │
                        ▼                                       │
        fetchers (方式 → RSS / RSSHub / API / Scraper / Email)  │
                        │                                       │
                        ▼                                       │
              content_item + fetch_run  ◀──────────────────────┘
                        │
                        ▼
                  FastAPI REST (/api/v1/...)
```

| Layer | Package | Responsibility |
|---|---|---|
| Catalog | `datahub.catalog` | Parse the workbook; define the 9 module standards (`module_spec.py`) |
| Models | `datahub.models` | ORM: `DataSource`, `FetchRun`, `ContentItem` |
| Schemas | `datahub.schemas` | Common + per-module content standards; API DTOs |
| Fetchers | `datahub.fetchers` | One fetcher per `方式` family; `registry.py` routes by method |
| Scheduler | `datahub.scheduler` | `频率` → trigger (`frequency.py`); APScheduler service |
| Ingest | `datahub.ingest` | Catalog upsert; fetch+store runner |
| API | `datahub.api` | FastAPI app + routers |
| CLI | `datahub.cli` | `init-db / ingest / list / run / serve / schedule` |

### Module standards (requirement 1)

`datahub/catalog/module_spec.py` defines, per category, what a content item
represents (`item_title`, from the sheet's 数据项标题) and its module-specific
payload fields. `datahub/schemas/content.py` provides a matching Pydantic
payload model per module on top of a shared `BaseContentItem`.

| Module | Tab | Item | Payload fields |
|---|---|---|---|
| news | 1_新闻 | 新闻标题 | region, topic, lang |
| events | 2_全球事件 | 事件标题 | event_type, actors, location, cameo_code |
| calendar | 3_日历 | 日期/事项 | event_date, calendar_type, symbol |
| company | 4_公司 | 公司名称 | symbol, exchange, data_type |
| market | 5_市场 | 可交易对象 | instrument, asset_class, venue |
| macro | 6_宏观 | 区域/国家指标 | country, indicator, period |
| opinion | 7_关键舆论平台 | 平台条目 | platform, topic, rank |
| channel | 8_关键频道 | 频道条目 | medium, topic, lang |
| person | 9_关键人物 | 人物动态 | person, platform, bio |

### Method → fetcher routing

| `方式` family | Fetcher | Status |
|---|---|---|
| 官方RSS / Google News / NewsAPI / YouTube / 公众号 | `RssFetcher` | live |
| RSSHub·微博 / 雪球 / B站 / RSSHub | `RsshubFetcher` | live |
| GDELT / ArXiv | `ApiFetcher` providers | live, key-free |
| FMP / FRED / twitterapi.io / ACLED | `ApiFetcher` providers | needs API key |
| 爬虫 / 官方(爬取) | `ScraperFetcher` | live (generic link extraction) |
| 邮件订阅 | `EmailSubscriptionFetcher` | stub (needs mailbox bridge) |

### Frequency → schedule

`实时/高频` → interval poll · `N分钟` → interval · `每日/每周/每月/每季/每年`
→ cron · `不定期/偶尔/按provider/(blank)` → manual (on-demand only).

## Quickstart

```bash
cd michelle_datahub
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

datahub init-db          # create tables
datahub ingest           # load the Excel registry into the catalog
datahub list --module news --limit 5
datahub run --source 1   # fetch one source now
datahub serve            # REST API at http://localhost:8000/docs
```

Run the scheduler as its own worker (set `DATAHUB_API_SCHEDULER=0` for the API):

```bash
datahub schedule
```

## REST API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness |
| GET | `/api/v1/modules` | module standards + source counts |
| GET | `/api/v1/sources` | list/filter catalog (`module`, `priority`, `method`, `q`) |
| GET | `/api/v1/sources/{id}` | source detail |
| POST | `/api/v1/sources/{id}/fetch` | fetch one source now |
| GET | `/api/v1/sources/{id}/runs` | recent fetch-run audit |
| GET | `/api/v1/content` | query fetched items (`module`, `source_id`, `since`, `q`) |
| GET | `/api/v1/jobs` | scheduler state |
| POST | `/api/v1/jobs/reload` | rebuild jobs from catalog |
| POST | `/api/v1/jobs/catalog/reload` | re-parse Excel, then rebuild jobs |

## Tests

```bash
pytest -q
```
