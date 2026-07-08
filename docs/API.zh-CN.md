# Michelle DataHub API 文档

- **Base URL**:生产 `https://mai.polarisagi.com`,本地 `http://127.0.0.1:8000`
- **格式**:JSON;所有时间为 UTC(ISO 8601)
- **鉴权**:无;生产环境 9–11 号调度接口仅限服务器本机访问
- **交互式文档**:`/docs`(Swagger UI)

---

## 一、API 汇总表

| # | API | 方法 | 路径 | 功能 |
|---|---|---|---|---|
| 1 | [健康检查](#1-健康检查) | GET | `/health` | 存活探针 |
| 2 | [内容类型列表](#2-内容类型列表) | GET | `/api/v1/modules` | 9 种内容类型的标准与源计数 |
| 3 | [按类型取内容](#3-按类型取内容) | GET | `/api/v1/content/{module}` | 某类型当天最新 N 条(核心接口) |
| 4 | [跨类型查内容](#4-跨类型查内容) | GET | `/api/v1/content` | 通用查询:按源/日期/关键词过滤 |
| 5 | [数据源列表](#5-数据源列表) | GET | `/api/v1/sources` | 按模块/优先级/方式筛选数据源 |
| 6 | [数据源详情](#6-数据源详情) | GET | `/api/v1/sources/{id}` | 单个数据源的注册信息 |
| 7 | [立即抓取](#7-立即抓取) | POST | `/api/v1/sources/{id}/fetch` | 同步抓取一个源并入库 |
| 8 | [抓取历史](#8-抓取历史) | GET | `/api/v1/sources/{id}/runs` | 某源的执行审计记录 |
| 9 | [调度状态](#9-调度状态) | GET | `/api/v1/jobs` | 调度器运行状态与任务表 |
| 10 | [重建任务](#10-重建任务) | POST | `/api/v1/jobs/reload` | 依当前目录重建调度任务 |
| 11 | [重载注册表](#11-重载注册表) | POST | `/api/v1/jobs/catalog/reload` | 重新解析 Excel 并重建任务 |
| 12 | [监控统计](#12-监控统计) | GET | `/api/v1/stats` | 全局数据统计(驱动监控页) |
| 13 | [监控页面](#13-监控页面) | GET | `/monitor` | 数据监控仪表盘(HTML) |

---

## 二、API 详细说明

### 1. 健康检查

`GET /health` — 存活探针,返回服务状态与注册表路径。无参数。

```bash
curl https://mai.polarisagi.com/health
```
```json
{"status": "ok", "catalog_path": "data/Michelle_Datasource_2026-06-02.xlsx"}
```

### 2. 内容类型列表

`GET /api/v1/modules` — 返回 9 种内容类型([ModuleOut](#moduleout) 数组),
含每类的 payload 字段定义和数据源数量。客户端初始化时调用一次即可。无参数。

```bash
curl https://mai.polarisagi.com/api/v1/modules
```
```json
[{"key": "news", "tab": "1_新闻", "display_name": "新闻", "item_title": "新闻标题",
  "payload_fields": ["region", "topic", "lang"],
  "note": "News-only feeds (RSS / Google News / NewsAPI).", "source_count": 385},
 …共 9 个]
```

### 3. 按类型取内容

`GET /api/v1/content/{module}` — **核心取数接口**。返回某类型在指定日期的最新
N 条([ContentItemOut](#contentitemout) 数组),默认**当天(UTC)**、最新 50 条。

| 参数 | 位置 | 类型 | 默认 | 说明 |
|---|---|---|---|---|
| `module` | path | string | 必填 | `news/events/calendar/company/market/macro/opinion/channel/person` |
| `date` | query | date | 当天(UTC) | 日历日,如 `2026-07-01` |
| `by` | query | string | `published` | 时间字段:`published` 发布时间 / `fetched` 入库时间 |
| `q` | query | string | — | 标题子串匹配(不区分大小写) |
| `limit` | query | int 1–500 | 50 | 返回最新 N 条 |
| `offset` | query | int | 0 | 分页偏移 |

错误:未知类型 → `404`;`by` 非法/日期格式错 → `422`。
注意:`by=published` 会排除无发布时间的条目,想要"当天入库的一切"用 `by=fetched`。

```bash
# 今天最新 20 条新闻(按入库时间)
curl "https://mai.polarisagi.com/api/v1/content/news?limit=20&by=fetched"
# 指定历史日期
curl "https://mai.polarisagi.com/api/v1/content/market?date=2026-07-01"
```
```json
[{"id": 1024, "source_id": 2, "module": "news",
  "external_id": "https://www.scmp.com/…",
  "title": "Hong Kong assets hit record US$5.38 trillion …",
  "url": "https://www.scmp.com/…", "summary": "…",
  "fulltext": "文章正文全文……", "published_at": "2026-07-04T08:15:00",
  "fetched_at": "2026-07-04T08:20:11", "payload": {"author": "…"}}]
```

### 4. 跨类型查内容

`GET /api/v1/content` — 通用查询,不限类型、`date` 无默认(不传则返回全库最新)。
适合全局搜索、按源取数、增量同步。返回 [ContentItemOut](#contentitemout) 数组,
按 `fetched_at` 倒序。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `module` | string | — | 按类型过滤 |
| `source_id` | int | — | 按数据源过滤 |
| `date` | date | — | 日历日(UTC) |
| `by` | string | `published` | `date` 所用时间字段 |
| `since` | datetime | — | `published_at >= since`,增量拉取用 |
| `q` | string | — | 标题子串匹配 |
| `limit` | int 1–500 | 50 | 页大小 |
| `offset` | int | 0 | 分页偏移 |

```bash
# 全库标题搜 "AI"
curl "https://mai.polarisagi.com/api/v1/content?q=AI&limit=10"
# 增量同步:某时间点后的 macro 内容
curl "https://mai.polarisagi.com/api/v1/content?module=macro&since=2026-07-01T00:00:00"
```

### 5. 数据源列表

`GET /api/v1/sources` — 查询注册表数据源([DataSourceOut](#datasourceout) 数组,按 id 排序)。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `module` | string | — | 精确匹配类型 |
| `priority` | string | — | 精确匹配优先级(如 `P1`) |
| `method` | string | — | `方式` 子串匹配(如 `RSS`、`twitterapi`) |
| `enabled` | bool | — | 是否启用 |
| `q` | string | — | 名称子串匹配 |
| `limit` | int ≤1000 | 100 | 页大小 |
| `offset` | int | 0 | 分页偏移 |

```bash
curl "https://mai.polarisagi.com/api/v1/sources?module=news&priority=P1&limit=2"
```
```json
[{"id": 1, "module": "news", "tab": "1_新闻", "l1_category": "1. Regional News",
  "l2_category": "Asia-Pacific", "name": "Asia News",
  "url": "https://news.google.com/rss/search?q=…", "method": "Google News RSS",
  "paid": "免费", "frequency": "10-15分钟", "priority": "P1", "health": "🟢",
  "enabled": true}]
```

### 6. 数据源详情

`GET /api/v1/sources/{id}` — 单个源的注册信息([DataSourceOut](#datasourceout))。
不存在 → `404`。

```bash
curl https://mai.polarisagi.com/api/v1/sources/2
```
```json
{"id": 2, "module": "news", "name": "South China Morning Post",
 "url": "https://www.scmp.com/rss/91/feed/", "method": "官方RSS",
 "paid": "免费", "frequency": "10-15分钟", "priority": "P1", "enabled": true, …}
```

### 7. 立即抓取

`POST /api/v1/sources/{id}/fetch` — **同步**抓取一个源:请求→抓取→排重入库→
返回摘要(秒级,取决于源响应速度)。适合调试某个源、或按需即时刷新。
源不存在 → `404`。

| 返回字段 | 说明 |
|---|---|
| `status` | `ok` / `error` / `skipped` |
| `fetched` | 本次抓到条数 |
| `new` | 排重后新入库条数 |
| `note` | 错误/跳过原因(成功时为 null) |

```bash
curl -X POST https://mai.polarisagi.com/api/v1/sources/2/fetch
```
```json
{"source_id": 2, "name": "South China Morning Post", "module": "news",
 "status": "ok", "fetched": 50, "new": 25, "note": null}
```

### 8. 抓取历史

`GET /api/v1/sources/{id}/runs` — 某源的执行审计([FetchRunOut](#fetchrunout)
数组,最新在前)。排查"某个源为什么没数据"的首选。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `limit` | int ≤200 | 20 | 返回条数 |

```bash
curl "https://mai.polarisagi.com/api/v1/sources/386/runs?limit=1"
```
```json
[{"id": 4108, "source_id": 386, "started_at": "2026-07-04T01:03:35",
  "finished_at": "2026-07-04T01:03:46", "status": "error",
  "item_count": 0, "new_count": 0,
  "error": "gdelt: Client error '429 Too Many Requests' …"}]
```

### 9. 调度状态

`GET /api/v1/jobs` — 调度器运行状态与任务表。
**仅服务器本机可访问**(nginx 封禁外网);且它反映的是**当前进程内嵌的调度器**,
分离部署(独立 worker)下返回 `running: false` 属正常。

```bash
curl http://127.0.0.1:8000/api/v1/jobs
```
```json
{"running": true, "jobs": [
  {"id": "refresh-all", "next_run_time": "2026-07-04T10:00:00+00:00",
   "trigger": "cron[hour='*/2', minute='0']"},
  {"id": "fulltext-enrich", "next_run_time": "…", "trigger": "interval[0:15:00]"},
  {"id": "src-2", "next_run_time": "…", "trigger": "interval[0:15:00]"}]}
```

### 10. 重建任务

`POST /api/v1/jobs/reload` — 依当前目录状态重建调度任务(启用/禁用源之后用)。
访问限制同上;分离部署下对独立 worker 无效,应重启 scheduler 服务。

```bash
curl -X POST http://127.0.0.1:8000/api/v1/jobs/reload
```
```json
{"reloaded": true,
 "by_kind": {"interval": 774, "cron": 414, "manual": 44, "refresh": 1},
 "total_jobs": 1189}
```

### 11. 重载注册表

`POST /api/v1/jobs/catalog/reload` — 重新解析 Excel 注册表入库(幂等 upsert),
然后重建调度任务。更新工作簿后使用。访问限制同 9/10。

```bash
curl -X POST http://127.0.0.1:8000/api/v1/jobs/catalog/reload
```
```json
{"catalog": {"created": 0, "updated": 1232, "skipped": 1, "total": 1233},
 "total_jobs": 1189}
```

### 12. 监控统计

`GET /api/v1/stats` — 一次返回全部监控聚合:总量、今日新增、正文覆盖、近 24
小时抓取执行(ok/error/skipped + 成功率)、分模块库存/今日/最新入库时间、最近
10 条失败记录。无参数。

```bash
curl https://mai.polarisagi.com/api/v1/stats
```
```json
{"generated_at": "2026-07-08T00:11:26+00:00",
 "totals": {"content": 79486, "today_new": 5713, "sources": 1232, "sources_enabled": 1232},
 "fulltext": {"extracted": 42009, "failed": 10324, "pending": 27153},
 "runs_24h": {"ok": 5660, "error": 2294, "skipped": 5580, "success_rate": 0.712},
 "last_fetch_at": "…", "modules": [{"module": "news", "total": 65214, "today": 5113, …}],
 "recent_errors": [{"source_id": …, "name": "…", "error": "…"}]}
```

### 13. 监控页面

`GET /monitor` — 自包含 HTML 仪表盘(内联样式脚本,无外部依赖,自适应深浅色,
每 60 秒自动刷新),内容:指标卡片(总量/今日/成功率/源数/正文覆盖率)、正文
覆盖与 24h 执行状态条、分模块今日入库条形表、近期失败列表。

**访问路径:`https://mai.polarisagi.com/monitor`**(本地 `http://127.0.0.1:8000/monitor`)。

---

## 三、附录

### 数据结构

#### ContentItemOut

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | 条目 id |
| `source_id` | int | 所属数据源 id |
| `module` | string | 内容类型 |
| `external_id` | string | 源侧唯一标识(与 `source_id` 组成排重键) |
| `title` | string \| null | 标题 |
| `url` | string \| null | 原文链接 |
| `summary` | string \| null | 摘要 |
| `fulltext` | string \| null | 正文全文;`null`=尚未抽取,`""`=抽取失败。Google News 链接自动解码原文后抽取,原文链接在 `payload.canonical_url` |
| `published_at` | datetime \| null | 发布时间(UTC) |
| `fetched_at` | datetime | 入库时间(UTC) |
| `payload` | object | 类型专属字段(见 `/api/v1/modules` 的 `payload_fields`) |

#### DataSourceOut

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | 源 id |
| `module` / `tab` | string | 类型 / Excel 标签页 |
| `l1_category` / `l2_category` | string \| null | 一级/二级分类 |
| `name` | string | 渠道名称 |
| `url` | string \| null | 来源链接 |
| `method` | string \| null | 抓取方式 |
| `paid` | string \| null | 是否付费 |
| `frequency` | string \| null | 更新频率 |
| `priority` | string \| null | 优先级 |
| `health` | string \| null | 健康度标记 |
| `enabled` | bool | 是否启用 |

#### FetchRunOut

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` / `source_id` | int | 记录 id / 源 id |
| `started_at` / `finished_at` | datetime | 开始/结束时间(UTC) |
| `status` | string | `ok` / `error` / `skipped` / `running` |
| `item_count` / `new_count` | int | 抓到条数 / 排重后新入库条数 |
| `error` | string \| null | 错误原因 |

#### ModuleOut

| 字段 | 类型 | 说明 |
|---|---|---|
| `key` | string | 类型 key(用于 `{module}` 参数) |
| `tab` / `display_name` | string | Excel 标签页 / 显示名 |
| `item_title` | string | 该类型条目 `title` 的含义 |
| `payload_fields` | string[] | `payload` 中的类型专属字段 |
| `source_count` | int | 该类型数据源数量 |

### 错误码

| 状态码 | 场景 | 响应示例 |
|---|---|---|
| `404` | 未知类型 / 源 id 不存在 | `{"detail": "unknown module 'foo'; one of […]"}` |
| `422` | 参数非法(`by`、日期格式、`limit` 越界) | FastAPI 标准校验错误结构 |
