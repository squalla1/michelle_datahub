# API 参考 — Michelle DataHub

> **语言:** [English](API_REFERENCE.md) | 中文

目录驱动数据引擎的 REST API。所有内容从数据源注册表抓取、存入数据库、每 2 小时
全量刷新一次(自动排重),并通过以下只读接口提供。

- **Base URL:** `http://<host>:8000`(默认端口 `8000`)
- **前缀:** 所有数据接口位于 `/api/v1` 下
- **格式:** JSON;所有时间戳均为 **UTC**(ISO 8601)
- **鉴权:** 无(若需对外暴露,请置于网关/反向代理之后)
- **交互式文档:** `GET /docs`(Swagger UI)、`GET /redoc`、`GET /openapi.json`
  —— 由代码自动生成,永远与实现一致。

代码位置:路由在 `datahub/api/routes/`,响应模型在 `datahub/schemas/`。

---

## 模块(内容类型)

内容分为 **9 种模块类型**。所有 `{module}` 路径参数和 `module` 查询参数使用下列 key:

| key | 中文 | 条目含义 |
|---|---|---|
| `news` | 新闻 | 一条新闻标题 |
| `events` | 全球事件 | 一个全球事件 |
| `calendar` | 日历 | 一个日程事项(财报、IR、经济数据……) |
| `company` | 公司 | 一条公司概况/财务/公告数据 |
| `market` | 市场 | 一条可交易对象数据 |
| `macro` | 宏观 | 一次宏观指标发布 |
| `opinion` | 关键舆论平台 | 一条舆论平台条目 |
| `channel` | 关键频道 | 一条频道条目(播客/博客/YouTube……) |
| `person` | 关键人物 | 一条人物动态 |

---

## 接口索引

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/health` | 存活探针 + 当前 catalog 路径 |
| GET | `/api/v1/modules` | 9 个模块标准 + 源计数 |
| GET | `/api/v1/content` | 通用跨模块内容查询 |
| GET | `/api/v1/content/{module}` | 按类型取数:当天最新 N 条 |
| GET | `/api/v1/sources` | 目录源列表(注册表行) |
| GET | `/api/v1/sources/{id}` | 按 id 查单个源 |
| POST | `/api/v1/sources/{id}/fetch` | 立即同步抓取一个源 |
| GET | `/api/v1/sources/{id}/runs` | 某源的近期抓取审计记录 |
| GET | `/api/v1/jobs` | 调度器状态 + 任务列表 |
| POST | `/api/v1/jobs/reload` | 依目录重建调度任务 |
| POST | `/api/v1/jobs/catalog/reload` | 重新解析 Excel 注册表并重建任务 |

---

## Health

### `GET /health`

存活探针。

**200** →
```json
{ "status": "ok", "catalog_path": "data/Michelle_Datasource_2026-06-02.xlsx" }
```

---

## Modules

### `GET /api/v1/modules`

返回 9 个模块各自的标准及其源数量。

**响应:** `ModuleOut[]`

| 字段 | 类型 | 说明 |
|---|---|---|
| `key` | string | 模块 key(见上表) |
| `tab` | string | Excel 标签页名 |
| `display_name` | string | 显示名 |
| `item_title` | string | 该模块内容条目 `title` 的含义 |
| `payload_fields` | string[] | `payload` 中的模块专属字段 |
| `note` | string | 简述 |
| `source_count` | int \| null | 该模块的目录源数量 |

**示例**
```bash
curl localhost:8000/api/v1/modules
```

---

## Content(内容)

核心数据接口。条目共享统一结构(`ContentItemOut`),模块专属字段在 `payload` 内。

### `ContentItemOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | 条目 id |
| `source_id` | int | 所属源(→ `/api/v1/sources/{id}`) |
| `module` | string | 模块 key |
| `external_id` | string | 源侧原生 id(与 `source_id` 组成排重键) |
| `title` | string \| null | 标题 |
| `url` | string \| null | 条目链接 |
| `summary` | string \| null | 摘要 |
| `published_at` | datetime \| null | 源发布时间(UTC) |
| `fetched_at` | datetime | 入库时间(UTC) |
| `payload` | object | 模块专属字段(见下方各模块标准) |

### `GET /api/v1/content/{module}` — 按类型取数(推荐)

取某模块类型在指定日期的最新 **N** 条。日期默认**当天(UTC)**。

| 参数 | 位置 | 类型 | 默认 | 说明 |
|---|---|---|---|---|
| `module` | path | string | — | 9 个模块 key 之一;未知 → **404** |
| `date` | query | date(`YYYY-MM-DD`) | 当天(UTC) | 要查询的日历日 |
| `by` | query | `published` \| `fetched` | `published` | `date` 过滤和排序所用的时间字段 |
| `q` | query | string | — | 标题子串匹配(不区分大小写) |
| `limit` | query | int(1–500) | 50 | 返回最新 N 条 |
| `offset` | query | int | 0 | 分页偏移 |

按所选 `by` 字段倒序(最新在前)。注意:`by=published` 时,没有发布时间的条目
(如爬虫抽取的链接)会被排除 —— 想拿到"当天入库的一切",用 `by=fetched`。

**示例**
```bash
# 今天最新 20 条新闻
curl "localhost:8000/api/v1/content/news?limit=20"
# 指定历史日期
curl "localhost:8000/api/v1/content/market?date=2026-06-21"
# 当天入库的全部条目(不管发布时间)
curl "localhost:8000/api/v1/content/person?by=fetched"
# 在当天事件中按标题搜索
curl "localhost:8000/api/v1/content/events?q=oil"
```

**响应:** `ContentItemOut[]`
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

### `GET /api/v1/content` — 通用查询

跨模块查询,`date` 无默认值(不筛选则返回全部日期的最新数据)。适合跨类型的
搜索与分页。

| 参数 | 位置 | 类型 | 默认 | 说明 |
|---|---|---|---|---|
| `module` | query | string | — | 按模块 key 过滤 |
| `source_id` | query | int | — | 按所属源过滤 |
| `date` | query | date | — | 日历日(UTC);无默认 |
| `by` | query | `published` \| `fetched` | `published` | `date` 过滤所用时间字段 |
| `since` | query | datetime | — | `published_at >= since` |
| `q` | query | string | — | 标题子串匹配 |
| `limit` | query | int(1–500) | 50 | 页大小 |
| `offset` | query | int | 0 | 分页偏移 |

按 `fetched_at` 倒序。

**响应:** `ContentItemOut[]`

### 各模块 `payload` 标准

每个模块允许额外字段(`extra="allow"`),以下为声明的标准字段:

| 模块 | `payload` 字段 |
|---|---|
| `news` | `region`, `topic`, `lang` |
| `events` | `event_type`, `actors`(string[]), `location`, `cameo_code` |
| `calendar` | `event_date`, `calendar_type`, `symbol` |
| `company` | `symbol`, `exchange`, `data_type` |
| `market` | `instrument`, `asset_class`, `venue` |
| `macro` | `country`, `indicator`, `period` |
| `opinion` | `platform`, `topic`, `rank`(int) |
| `channel` | `medium`, `topic`, `lang` |
| `person` | `person`, `platform`, `bio` |

---

## Sources(目录源)

注册表行本身 —— 数据源的元信息,不是其内容。

### `DataSourceOut`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | 源 id |
| `module` | string | 模块 key |
| `tab` | string | Excel 标签页 |
| `l1_category` / `l2_category` | string \| null | 注册表分类 |
| `name` | string | 源名称 |
| `url` | string \| null | 源 URL |
| `method` | string \| null | `方式` —— 如何抓取 |
| `paid` | string \| null | 付费/免费标记 |
| `frequency` | string \| null | `频率` —— 多久抓一次 |
| `priority` | string \| null | 如 `P1` |
| `health` | string \| null | 健康度标记 |
| `enabled` | bool | 是否参与调度/抓取 |

### `GET /api/v1/sources`

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `module` | string | — | 精确匹配模块 key |
| `priority` | string | — | 精确匹配优先级(如 `P1`) |
| `method` | string | — | `方式` 子串匹配 |
| `enabled` | bool | — | 按启用状态过滤 |
| `q` | string | — | 名称子串匹配 |
| `limit` | int(≤1000) | 100 | 页大小 |
| `offset` | int | 0 | 分页偏移 |

**响应:** `DataSourceOut[]`(按 id 排序)

### `GET /api/v1/sources/{id}`

单个源。不存在 → **404**。**响应:** `DataSourceOut`

### `POST /api/v1/sources/{id}/fetch`

**立即同步**抓取一个源(抓取 + 排重落库 + 记录一次 run)。源不存在 → **404**。

**响应**(摘要):
```json
{
  "source_id": 2, "name": "South China Morning Post", "module": "news",
  "status": "ok", "fetched": 50, "new": 12, "note": null
}
```
`status` ∈ `ok` / `error` / `skipped`;`fetched` = 本次抓到的条数;`new` = 排重后
新入库条数。

### `GET /api/v1/sources/{id}/runs`

某源的近期抓取审计记录,最新在前。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `limit` | int(≤200) | 20 | 返回条数 |

**响应:** `FetchRunOut[]`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | run id |
| `source_id` | int | 源 |
| `started_at` | datetime | 开始时间(UTC) |
| `finished_at` | datetime \| null | 结束时间(UTC) |
| `status` | string | `ok` / `error` / `skipped` / `running` |
| `item_count` | int | 本次抓到条数 |
| `new_count` | int | 排重后新入库条数 |
| `error` | string \| null | 错误/跳过原因 |

---

## Jobs(调度控制)

### `GET /api/v1/jobs`

调度器状态与当前任务表(各源`频率`任务 + 每 2 小时的全局 `refresh-all` 任务)。

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

依当前目录状态重建调度任务(例如启用/禁用了某些源之后)。

```json
{ "reloaded": true, "by_kind": {"interval": 774, "cron": 414, "manual": 44, "refresh": 1}, "total_jobs": 1189 }
```

### `POST /api/v1/jobs/catalog/reload`

重新解析 Excel 注册表入库,然后重建任务。更新工作簿后使用。

```json
{ "catalog": {"created": 0, "updated": 3, "skipped": 1, "total": 1233}, "total_jobs": 1189 }
```

---

## 错误

标准 FastAPI 错误结构:
```json
{ "detail": "unknown module 'foo'; one of ['calendar', 'channel', 'company', 'events', 'macro', 'market', 'news', 'opinion', 'person']" }
```

| 状态码 | 场景 |
|---|---|
| `404` | 未知 `{module}` 或源 id 不存在 |
| `422` | 参数非法(如 `by` 不是 `published`/`fetched`、日期格式错误、`limit` 超范围) |

---

## 使用注意

- 数据由调度器(2 小时全量刷新 + 各源自身节奏)及 `POST /api/v1/sources/{id}/fetch`
  填充。刚初始化的库在首次抓取/刷新前是空的。
- 排重键为 `(source_id, external_id)`,重复刷新只新增真正的新条目 —— 轮询和重抓
  都是安全的。
- 无时间戳的源其 `published_at` 为空;想看"今天到了什么"而非"今天发布了什么",
  用 `by=fetched`。
