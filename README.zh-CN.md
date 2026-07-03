# Michelle DataHub

> **语言:** [English](README.md) | 中文

一个目录驱动(catalog-driven)的后端服务:**周期性抓取 `data/Michelle_Datasource_2026-06-02.xlsx`
中定义的数据源内容**,并通过 REST API 对外提供。

该 Excel 工作簿被视为*数据源注册表*:9 个标签页各对应一个**模块**,每一行是一个
**数据源**,声明其抓取方式(`方式`列)与抓取频率(`频率`列)。DataHub 解析注册表、
按频率为每个源调度抓取任务(另有每 2 小时一次的全量刷新,自动排重)、把结果规范化为
各模块的内容标准,并通过 HTTP 提供查询。

**文档导航**

| 文档 | 用途 |
|---|---|
| [docs/API_REFERENCE.zh-CN.md](docs/API_REFERENCE.zh-CN.md) | REST API 完整参考([English](docs/API_REFERENCE.md)) |
| [docs/DEPLOY.zh-CN.md](docs/DEPLOY.zh-CN.md) | PostgreSQL 打包部署指南([English](docs/DEPLOY.md)) |
| [docs/SOURCES_CONNECTIVITY.zh-CN.md](docs/SOURCES_CONNECTIVITY.zh-CN.md) | 信息源连通性报告(直连 vs 代理、解锁路线) |
| [deploy/schema.sql](deploy/schema.sql) | PostgreSQL 权威建表 DDL |
| `/docs`(服务运行后) | 自动生成的 Swagger 交互文档 |

## 为什么用 Python

注册表中约 60% 是 RSS/Atom 订阅源,其余以 HTML 抓取和 Python 原生数据 API
(AKShare、GDELT、ArXiv)为主。`feedparser`、`httpx`、`BeautifulSoup`、FastAPI、
APScheduler、SQLAlchemy 组合起来,比 Java 同类方案轻得多。

## 架构

```
Excel 注册表 ──> catalog(解析 + 模块标准)
                      │
                      ▼
                 data_source 表
                      │
      scheduler(频率 → interval/cron;全局 2 小时刷新) ── 手动即时抓取 ──┐
                      │                                                  │
                      ▼                                                  │
      fetchers(方式 → RSS / RSSHub / API / 爬虫 / 邮件)                 │
                      │                                                  │
                      ▼                                                  │
            content_item + fetch_run(按 source_id+external_id 排重)◀───┘
                      │
                      ▼
                FastAPI REST(/api/v1/...)
```

| 层 | 包 | 职责 |
|---|---|---|
| Catalog | `datahub.catalog` | 解析工作簿;定义 9 个模块标准(`module_spec.py`) |
| Models | `datahub.models` | ORM:`DataSource`、`FetchRun`、`ContentItem` |
| Schemas | `datahub.schemas` | 通用 + 各模块内容标准;API DTO |
| Fetchers | `datahub.fetchers` | 每个`方式`族一个 fetcher;`registry.py` 按方式路由 |
| Scheduler | `datahub.scheduler` | `频率` → 触发器(`frequency.py`);APScheduler 服务 + 全局 2h 刷新 |
| Ingest | `datahub.ingest` | 注册表入库;抓取+排重落库(`run_source` / `run_all_sources`) |
| API | `datahub.api` | FastAPI 应用 + 路由 |
| CLI | `datahub.cli` | `init-db / ingest / list / run / refresh / serve / schedule` |

### 模块标准

`datahub/catalog/module_spec.py` 按类别定义内容条目的含义(`item_title`,来自表头的
数据项标题)及模块专属 payload 字段;`datahub/schemas/content.py` 在共享的
`BaseContentItem` 之上为每个模块提供对应的 Pydantic payload 模型。

| 模块 | 标签页 | 条目含义 | payload 字段 |
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

### 方式 → fetcher 路由

| `方式`族 | Fetcher | 状态 |
|---|---|---|
| 官方RSS / Google News / NewsAPI·RSS 混合 / YouTube / 公众号 | `RssFetcher` | 可用 |
| RSSHub·微博 / 雪球 / B站 / RSSHub | `RsshubFetcher` | 可用(建议自建并配置 `DATAHUB_RSSHUB_BASE_URL`) |
| GDELT / ArXiv | `ApiFetcher` provider | 可用,免密钥 |
| FMP / FRED / twitterapi.io / ACLED | `ApiFetcher` provider | 需 API 密钥 |
| 其他 `* API` 方式(AKShare、EIA 等) | `ApiFetcher` | 待补 provider 插件,当前跳过 |
| 爬虫 / 官方(爬取) | `ScraperFetcher` | 可用(通用链接抽取) |
| 邮件订阅 | `EmailSubscriptionFetcher` | 桩实现(需邮箱网关) |

### 频率 → 调度

`实时/高频` → 间隔轮询 · `N分钟` → 间隔 · `每日/每周/每月/每季/每年` → cron ·
`不定期/偶尔/按provider/(空)` → 手动(仅按需触发)。
在各源自身节奏之外,全局 `refresh-all` 任务每 2 小时重抓一次全部启用源
(`DATAHUB_REFRESH_ALL_HOURS`);排重保证幂等。

## 快速开始

```bash
cd michelle_datahub
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

datahub init-db          # 建表
datahub ingest           # 把 Excel 注册表载入目录
datahub list --module news --limit 5
datahub run --source 1   # 立即抓取一个源
datahub refresh          # 全量抓取所有启用源一次(排重)
datahub serve            # REST API → http://localhost:8000/docs
```

调度器独立进程运行(API 侧设 `DATAHUB_API_SCHEDULER=0`):

```bash
datahub schedule
```

## REST API

完整参考:[docs/API_REFERENCE.zh-CN.md](docs/API_REFERENCE.zh-CN.md)。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/health` | 存活探针 |
| GET | `/api/v1/modules` | 模块标准 + 源计数 |
| GET | `/api/v1/content/{module}` | **按类型取数**:当天最新 N 条(`date`、`by`、`limit`) |
| GET | `/api/v1/content` | 通用查询(`module`、`source_id`、`date`、`since`、`q`) |
| GET | `/api/v1/sources` | 目录列表/筛选(`module`、`priority`、`method`、`q`) |
| GET | `/api/v1/sources/{id}` | 源详情 |
| POST | `/api/v1/sources/{id}/fetch` | 立即抓取一个源 |
| GET | `/api/v1/sources/{id}/runs` | 近期抓取审计记录 |
| GET | `/api/v1/jobs` | 调度器状态(含 `refresh-all`) |
| POST | `/api/v1/jobs/reload` | 依目录重建调度任务 |
| POST | `/api/v1/jobs/catalog/reload` | 重新解析 Excel 并重建任务 |

## 存储

开发默认 SQLite(零配置);生产用 PostgreSQL:
`DATAHUB_DATABASE_URL=postgresql+psycopg://...`(需安装 `[postgres]` extra)。
详见 [docs/DEPLOY.zh-CN.md](docs/DEPLOY.zh-CN.md)。

## 测试

```bash
pytest -q
```
