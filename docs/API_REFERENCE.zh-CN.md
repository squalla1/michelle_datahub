# API 参考 — Michelle DataHub

> **语言:** [English](API_REFERENCE.md) | 中文

目录驱动数据引擎的 REST API。所有内容从数据源注册表抓取、存入数据库、每 4 小时
全量刷新一次(自动排重),并通过以下只读接口提供。

- **Base URL:** 生产 `https://mai.polarisagi.com`;本地 `http://<host>:8000`
- **前缀:** 所有数据接口位于 `/api/v1` 下
- **格式:** JSON;所有时间戳均为 **UTC**(ISO 8601)
- **鉴权:** 无 —— 生产环境由 nginx 封禁外网访问 `/api/v1/jobs`,其余接口公开可读
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

## 数据源现状(接口能取到什么)

内容来自注册表的 **1232 个数据源**,已全部做过联通验证(实抓 + 接口可达性探测):
**931 个(76%)联通正常**,其中 **519 个当前即可取数(2026-08-02 起 FMP 付费 key
已接入,28 个 FMP 源转为出数)、282 个取数需付费待开通、64 个为免费官方 API**;
240 个不可联通,61 个无链接可验证。这直接决定各模块接口的数据丰度:

| 模块 | 源数 | ✅可取数 | 数据现状与说明 |
|---|---|---|---|
| `news` | 385 | 335 | ✅ 最丰富,日增数千条 |
| `channel` | 316 | 112 | ✅ 播客/博客/YouTube;126 个链接失效/不可达,61 个无链接 |
| `person` | 286 | 0 | 🟡 **256 个源联通正常但需付费(twitterapi.io,$0.15/千条),开通后即有数据** |
| `market` | 59 | 24 | ✅ **FMP 已接入(2026-08-02)**:9 家交易所行情、指数/外汇/加密/商品、美债收益率曲线共 21 源实际出数;🟢 18 个免费官方 API 联通正常 |
| `macro` | 50 | 3 | 🟢 24 个免费官方统计 API(世行/央行等)联通正常;19 个不可联通;FRED 插件已装待服务器端验证 |
| `opinion` | 42 | 5 | ❌ 30 个不可联通(微博/知乎/Reddit 反爬) |
| `calendar` | 39 | 13 | ✅ 含 5 个 FMP 日历源(财报/分红/IPO/经济,已接入);🟡 Finnhub 经济日历需升级套餐 |
| `company` | 33 | 12 | 🟡 FMP key 已配,财务源待在注册表「账号」列填监控股票清单后出数;另 11 个需付费 |
| `events` | 22 | 15 | ✅ GDELT 可用(偶发限流);✅ 2 个 FMP 事件源已接入(并购/IPO);其余 2 个需付费。注:注册表在此页还登记了 GitHub/Show HN 技术事件源(条目量大),按 `source_id` 可区分 |

完整分析(失败原因、解锁路线):[SOURCES_CONNECTIVITY.zh-CN.md](SOURCES_CONNECTIVITY.zh-CN.md);
逐源明细:[reports/connectivity_report.csv](reports/connectivity_report.csv)。

**用接口自查源信息**(源的元数据、连通状态都可在线查):

```bash
# 某模块的源清单(url/方式/频率/优先级)
curl "https://mai.polarisagi.com/api/v1/sources?module=opinion&limit=1"
# [{"id":589,"module":"opinion","l1_category":"1. 微博","name":"微博财经话题榜",
#   "url":"https://s.weibo.com/top/summary?cate=socialevent","method":"RSSHub·微博",
#   "frequency":"每15分钟","priority":"P1","enabled":true}]

# 找出所有需付费的 twitterapi.io 源(person 模块)
curl "https://mai.polarisagi.com/api/v1/sources?method=twitterapi&limit=1"
# [{"id":947,"module":"person","name":"Fei-Fei Li","url":"https://x.com/drfeifei",
#   "method":"twitterapi.io","paid":"$0.15/千条,按量无月费","frequency":"实时","priority":"P1"}]

# 判断某个源是否连通:看它的抓取历史(此例:GDELT 被限流)
curl "https://mai.polarisagi.com/api/v1/sources/386/runs?limit=1"
# [{"id":4108,"source_id":386,"status":"error","item_count":0,
#   "error":"gdelt: Client error '429 Too Many Requests' …"}]
```

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
| GET | `/api/v1/stats` | 全局监控统计(总量/正文覆盖/24h 执行/分模块) |
| GET | `/monitor` | 数据监控仪表盘页面(HTML,60s 自动刷新) |
| GET | `/api/v1/reports` | 刷新统计报告清单 |
| GET | `/api/v1/reports/{name}` | 查看/下载单份报告(`?download=1`);页面版 `/reports` |

---

## 使用示例(每个接口一个 case,真实响应)

以下响应均对生产数据库实测采集,长内容以 `…` 截断。

**1. 健康检查** —— 负载均衡/监控探活:
```bash
curl https://mai.polarisagi.com/health
# {"status":"ok","catalog_path":"data/Michelle_Datasource_2026-06-02.xlsx"}
```

**2. 发现 9 种内容类型** —— 客户端初始化时拉一次,获知类型与 payload 字段:
```bash
curl https://mai.polarisagi.com/api/v1/modules
# [{"key":"news","tab":"1_新闻","display_name":"新闻","item_title":"新闻标题",
#   "payload_fields":["region","topic","lang"],"source_count":385}, … 共9个]
```

**3. 按类型取当天最新 N 条**(核心接口)—— 例:每小时拉一次今日新闻流:
```bash
curl "https://mai.polarisagi.com/api/v1/content/news?limit=20&by=fetched"
# [{"id":…,"module":"news","title":"Daniel W. Drezner - Bulletin of the Atomic Scientists",
#   "url":"https://news.google.com/rss/articles/…","published_at":"2026-07-03T…","payload":{…}}, …]
```
变体:`?date=2026-07-01` 取历史某天;`by=published`(默认)按发布时间、`by=fetched` 按入库时间。

**4. 跨类型搜索** —— 例:全库标题搜 "AI":
```bash
curl "https://mai.polarisagi.com/api/v1/content?q=AI&limit=10"
# [{"title":"Hong Kong bookseller Lam Wing-kee, once detained by China, dies in Taipei", …}]
```
变体:`?module=macro&since=2026-07-01T00:00:00` 增量拉取;`?source_id=2` 看单源内容。

**5. 筛选数据源目录** —— 例:查看新闻类 P1 优先级的源:
```bash
curl "https://mai.polarisagi.com/api/v1/sources?module=news&priority=P1&limit=2"
# [{"id":1,"name":"Asia News","method":"Google News RSS","frequency":"10-15分钟",
#   "priority":"P1","enabled":true}, …]
```
变体:`?method=RSSHub` 按方式子串筛;`?enabled=false` 找被禁用的源。

**6. 单个源详情:**
```bash
curl https://mai.polarisagi.com/api/v1/sources/2
# {"id":2,"name":"South China Morning Post","url":"https://www.scmp.com/rss/91/feed/",
#  "method":"官方RSS","frequency":"10-15分钟","priority":"P1","enabled":true}
```

**7. 立即抓取一个源**(同步)—— 例:调试某个源是否正常:
```bash
curl -X POST https://mai.polarisagi.com/api/v1/sources/2/fetch
# {"source_id":2,"name":"South China Morning Post","status":"ok","fetched":50,"new":25,"note":null}
```

**8. 查看某源抓取历史**(审计)—— 例:排查一个源为什么没数据:
```bash
curl "https://mai.polarisagi.com/api/v1/sources/2/runs?limit=2"
# [{"id":2489,"started_at":"2026-07-03T21:23:48","status":"ok","item_count":50,
#   "new_count":25,"error":null}, …]
```

**9–11. 调度控制** —— nginx 已封禁外网访问,只能在服务器本机调用。分离部署下它们
只反映 API 进程;要管理 worker 请直接重启 scheduler 服务:
```bash
curl http://127.0.0.1:8000/api/v1/jobs
# {"running":false,"jobs":[]}        ← 分离部署下 false 是正常的

curl -X POST http://127.0.0.1:8000/api/v1/jobs/reload
# {"reloaded":true,"by_kind":{"interval":774,"cron":414,"manual":44,"refresh":1},"total_jobs":1189}

curl -X POST http://127.0.0.1:8000/api/v1/jobs/catalog/reload   # Excel 注册表更新后
# {"catalog":{"created":0,"updated":1232,"skipped":1,"total":1233}, …}
```

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
| `image_url` | string \| null | 配图 —— 抓取时取 feed 的 `media:*`/enclosure,正文富化时用页面 `og:image` 补齐 |
| `fulltext` | string \| null | 抽取的正文全文(`null`=尚未尝试,`""`=抽取失败) |
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
| `event_from` | query | date | — | 仅日历:`payload.event_date` ≥ 该日 |
| `event_to` | query | date | — | 仅日历:`payload.event_date` ≤ 该日 |
| `q` | query | string | — | 标题子串匹配(不区分大小写) |
| `limit` | query | int(1–500) | 50 | 返回最新 N 条 |
| `offset` | query | int | 0 | 分页偏移 |

按所选 `by` 字段倒序(最新在前)。注意:`by=published` 时,没有发布时间的条目
(如爬虫抽取的链接)会被排除 —— 想拿到"当天入库的一切",用 `by=fetched`。

**日程区间(calendar)**:`event_from`/`event_to` 按条目**自身的排期日期**筛选,
而不是入库日;传了区间即不再套用"当天"默认,一次请求即可取到"未来三周有什么",
无需全量翻页。结果按事件日期**升序**返回(日程的自然读法),无 `event_date` 的
条目不纳入。日历窗口为**回溯 7 天 + 前瞻 28 天**。

**低频回退**:不传 `date` 且当天窗口为空时(calendar/macro/market 等低频模块
可能连续数日无新条目),接口回退返回**全库最新 N 条**而不是 `[]`;显式传
`date=` 则不回退。

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
# 未来三周的日历事件,按排期升序
curl "localhost:8000/api/v1/content/calendar?event_from=2026-08-15&event_to=2026-09-05&limit=200"
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
    "image_url": "https://example.com/hero.jpg",
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
| `by` | query | `published` \| `fetched` | `published` | `date` 过滤所用时间字段(**只影响过滤,不影响排序**) |
| `order` | query | `fetched` \| `published` | `fetched` | 排序字段,倒序(最新在前) |
| `since` | query | datetime | — | `published_at >= since` |
| `event_from` | query | date | — | `payload.event_date >= 该日`(日历) |
| `event_to` | query | date | — | `payload.event_date <= 该日`(日历) |
| `q` | query | string | — | 标题子串匹配 |
| `limit` | query | int(1–500) | 50 | 页大小 |
| `offset` | query | int | 0 | 分页偏移 |

按 `order` 字段倒序(默认 `fetched_at`),并以 `id` 倒序作为第二排序键 —— 同一批写入的
条目(如某日的美债收益率曲线)共享同一个 `fetched_at`,没有第二排序键时批内顺序不确定。

注意 `published_at` 的语义随模块而变:`calendar` 条目的 `published_at` 是**事件日期**,
所以刚抓回来的条目也可能显示很早的日期。

**响应:** `ContentItemOut[]`

### 各模块 `payload` 标准

每个模块允许额外字段(`extra="allow"`),以下为声明的标准字段:

| 模块 | `payload` 字段 |
|---|---|
| `news` | `region`, `topic`, `lang` |
| `events` | `event_type`, `actors`(string[]), `location`, `cameo_code` |
| `calendar` | `event_date`, `event_timezone`, `calendar_type`, `calendar_region`, `symbol` |
| `company` | `symbol`, `exchange`, `data_type`, `logo_url` |
| `market` | `instrument`, `asset_class`, `venue`, `symbol`, `price`, `change`, `volume` |
| `macro` | `country`, `indicator`, `period`, `value`, `unit`, `frequency` |
| `opinion` | `platform`, `topic`, `rank`(int) |
| `channel` | `medium`, `topic`, `lang`, `audio_url`(+`audio_mime`/`audio_duration`), `video_url`(+`video_id`) |
| `person` | `person`, `platform`, `bio` |

> **媒体字段**:`audio_url`/`video_url` 取自播客/视频 feed 的 enclosure
> (YouTube 源另带 `video_id`)。`company.logo_url` 在读取时由 `symbol` 派生
> (公开 logo CDN,模板 `DATAHUB_STOCK_LOGO_SERVICE_URL`)—— 只要 `symbol`
> 有值即返回。

> **`calendar_type` 为封闭值域**(事件种类,而非市场):
> `财报 / 分红 / 拆股 / IPO / 公司行动 / 公司IR / 监管备案 / 经济 / 央行 /
> 国债拍卖 / 能源商品 / 加密事件 / 科技活动`。所属市场/地区迁至 `calendar_region`
> (`全球`、`美国`、`A股`、`港交所信披` …)。`event_timezone` 标明 `event_date`
> 的时间基准,经济日历为 **UTC**(美国 7 月 CPI 记为 `2026-08-12 12:30:00`,
> 即美东 08:30)。
> **`event_date` 必然存在**:calendar 模块的条目若无 `event_date` 一律不入库,
> 因此日历接口不会再混入站点自身的导航/栏目链接。

> **`asset_class` 为封闭值域**:`股票 / 指数 / 外汇 / 商品 / 加密货币 / 债券`。
> 取自行情接口本身,不再取注册表 L1(那是"二级市场"这类市场分层)。
> `benchmark: true` 标记各类基准 symbol,每轮必采,不受成交量排名影响。

> **`macro.unit`** 由固定的"指标→单位"对照表下发(`%`、`百分点`、`千人`、
> `十亿美元`、`指数 (1982-84=100)` …);请勿由数值反推单位。

> **填充现状**:`region/topic/platform/medium/asset_class` 等**源侧字段**由注册表
> 分类在入库时自动回填(含存量,2026-07-07 起)。**数值型字段自 2026-08-02 起
> 由 FMP/FRED provider 真实填充**:market 行情条目带 `symbol/price/change/volume`,
> calendar 条目带 `symbol/event_date` 及 EPS/分红/IPO 明细,债市带完整收益率曲线,
> 经济日历带 `actual/estimate/previous`(需配置对应 API key)。NLP 派生字段
> (实体/情绪)按分工由下游引擎生成,API 不做。Google News 条目解码出的原文链接
> 存于 `payload.canonical_url`。

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
| `icon_url` | string \| null | 源域名的 64px favicon(服务模板 `DATAHUB_FAVICON_SERVICE_URL`,可换国内可达服务) |
| `avatar_url` | string \| null | 源头像;当前与 `icon_url` 相同,接入各平台头像源后升级为真实头像 |

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

> 这些接口操作的是 **API 进程内嵌的调度器**。分离部署时(`DATAHUB_API_SCHEDULER=0`
> + 独立 `datahub schedule` worker)它们返回 `running: false` / 不产生任何影响 ——
> 应直接管理 worker 进程(重启即重建任务)。

### `GET /api/v1/jobs`

调度器状态与当前任务表(各源`频率`任务 + 每 4 小时的全局 `refresh-all` 任务)。

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

- 数据由调度器(4 小时全量刷新 + 各源自身节奏)及 `POST /api/v1/sources/{id}/fetch`
  填充。刚初始化的库在首次抓取/刷新前是空的。
- 排重键为 `(source_id, external_id)`,重复刷新只新增真正的新条目 —— 轮询和重抓
  都是安全的。
- 无时间戳的源其 `published_at` 为空;想看"今天到了什么"而非"今天发布了什么",
  用 `by=fetched`。
- `fulltext` 由富化任务异步填充(入库后约 15 分钟内);刚入库的条目可能还是
  `null`,`""` 表示抽取失败(付费墙/反爬)。**Google News 加密链接会先自动解码出
  原文地址再抽取**,原文链接存于 `payload.canonical_url`(供去重/溯源);正文页
  若带发布时间,会顺带回填缺失的 `published_at`。
- **低频模块的查询口径**:`macro`/`calendar` 等模块条目常无发布时间或非每日更新,
  默认查询(当天 + `by=published`)会显示为空 —— 请用 `by=fetched`(按入库时间)
  或显式指定 `date`。
- **保留期:** 只保留最近 7 天的内容(`DATAHUB_RETENTION_DAYS`),更早的每日清理。
  计龄按首次入库时间;去重命中不刷新该时间,因此源里仍在提供的条目也会到期删除,
  并在下一轮刷新时重建。
