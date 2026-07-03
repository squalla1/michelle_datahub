# 信息源连通性报告

> 基于注册表 `data/Michelle_Datasource_2026-06-02.xlsx`(1232 个源)。
> 实测两轮:**直连** 2026-07-02、**代理**(`127.0.0.1:7897`)2026-07-04;
> 24 并发、单源超时 15s,直接调用各 fetcher(不写库)。
> 逐源明细:[`reports/connectivity_report.csv`](reports/connectivity_report.csv)。

## 结论(TL;DR)

- **1232 个源中 767 个(62%)当前代码可直接抓取,实测约 542–547 个(70% 的可抓源)真实返回数据。**
- **网络代理不是瓶颈**:代理只救回 6 个源,反而让 11 个失败(共享出口 IP 触发 GDELT/Reddit 限流)。失败主因是源本身失效(404)、反爬(403)、限流(429)和注册表 URL 数据质量。
- 最大的数据缺口是 **person 模块(262 个 twitterapi.io 源)—— 配一把 API 密钥即可解锁 21% 的注册表**。

## 1. 全量 1232 源:实现状况总览

| 状态类 | 数量 | 占比 | 含义 |
|---|---|---|---|
| 🟢 LIVE_RSS | 660 | 54% | RSS/Atom,代码已实现,可抓 |
| 🟢 LIVE_RSSHUB | 52 | 4% | 经 RSSHub 桥接,可抓(部分依赖公共实例) |
| 🟢 LIVE_SCRAPE | 40 | 3% | 通用爬虫(链接抽取),可抓 |
| 🟢 LIVE_API | 15 | 1% | GDELT/ArXiv,免密钥 provider 已实现 |
| 🟡 SKIP_NEEDS_KEY | 297 | 24% | provider 桩已就位,**缺 API 密钥** |
| 🔴 SKIP_NO_PROVIDER | 99 | 8% | 路由到 ApiFetcher 但**无插件**(AKShare/央行/SEC 等 70+ 种) |
| 🔴 SKIP_NO_URL | 40 | 3% | 注册表行内无可抓 URL |
| 🔴 SKIP_EMAIL | 21 | 2% | 邮件订阅,需邮箱网关 |
| 🔴 NO_FETCHER | 8 | 1% | `方式` 无任何 fetcher 匹配 |

> 说明:2026-07-02 修复了 NewsAPI/RSS 混合方式的路由 Bug,74 个源从
> SKIP_NO_PROVIDER 转入 LIVE_RSS(实测 71 个可抓)。

## 2. 实测:直连 vs 代理(767 个 LIVE 源)

| 轮次 | ok | error | exc(URL 非法) | 成功率 |
|---|---|---|---|---|
| 直连(07-02) | 547 | 181 | 39 | 71.3% |
| 代理(07-04) | 542 | 186 | 39 | 70.7% |

状态迁移:**稳定成功 536 · 稳定失败 175 · 代理救回 6 · 代理反损 11 · URL 非法 39(两轮均无法请求)**

- 救回的 6 个全部是官方 RSS(VnExpress、Cointelegraph、TechCabal、r/investing 等)—— 直连时的偶发网络问题。
- 反损的 11 个:GDELT×4 与 Reddit 因**代理出口 IP 被限流**(429),另有数个站点对代理出口 SSL 拒绝。
- **结论:生产环境无需为抓取配置代理**;若配置,应排除 GDELT/Reddit 等限流敏感域。

按 fetcher 族(代理轮):

| 类别 | ok / 总数 | 成功率 |
|---|---|---|
| LIVE_RSS | 481 / 660 | 73% |
| LIVE_RSSHUB | 32 / 52 | 62% |
| LIVE_SCRAPE | 25 / 40 | 62% |
| LIVE_API(GDELT/ArXiv) | 4 / 15 | 27%(GDELT 限流所致,直连为 53%) |

## 3. 模块 × 实测状态(代理轮,仅 LIVE 源)

| 模块 | ok | error | exc | LIVE 源计 | 备注 |
|---|---|---|---|---|---|
| news | 345 | 40 | 0 | 385 | 最健康,90% 可抓 |
| channel | 129 | 87 | 39 | 255 | exc 全部集中在此(URL 数据质量) |
| person | 21 | 3 | 0 | 24 | 另有 262 个 twitterapi.io 源待密钥 |
| opinion | 10 | 30 | 0 | 40 | 反爬重灾区(微博/知乎/Reddit) |
| calendar | 12 | 7 | 0 | 19 | |
| company | 13 | 1 | 0 | 14 | |
| events | 3 | 11 | 0 | 14 | GDELT 限流 |
| macro | 5 | 6 | 0 | 11 | |
| market | 4 | 1 | 0 | 5 | 大多数 market 源在 SKIP_NEEDS_KEY |

## 4. 失败原因分析(代理轮 225 个失败)

| 原因 | 数量 | 处置建议 |
|---|---|---|
| HTTP 404(feed 失效) | 77 | 注册表修订 URL 或置 `enabled=false` |
| SSL 握手失败 | 42 | 多为境内政府站/小站,需逐个核查 |
| URL 含非法字符 | 39 | **注册表数据质量问题**,fetch 前清洗 URL 可救回 |
| HTTP 429(限流) | 37 | GDELT/Google News/Reddit;加退避重试 + 错峰调度 |
| HTTP 403(反爬) | 17 | 通用 UA 被拒;需定制头/渲染或放弃 |
| HTTP 432 / 超时 / 其他 | 13 | 个案处理 |

## 5. 各 `方式` 族实现状况

| `方式` 族 | Fetcher | 实现状态 |
|---|---|---|
| 官方RSS / Google News / YouTube / 公众号桥接 / NewsAPI·RSS 混合 | `RssFetcher` | ✅ 已实现,实测 73% 可抓 |
| RSSHub 系(微博/雪球/B站/即刻) | `RsshubFetcher` | ✅ 已实现;公共实例 `rsshub.app` 返回 403,**建议自建** |
| GDELT / ArXiv | `ApiFetcher` provider | ✅ 已实现免密钥;GDELT 需加限流退避 |
| twitterapi.io(262)/ FMP(29)/ FRED(3)/ ACLED(3) | `ApiFetcher` 桩 | 🟡 代码就位,**等密钥**(`DATAHUB_*_API_KEY`) |
| AKShare(18)及其余 70+ 种 API | `ApiFetcher` | 🔴 无 provider 插件,按需在 `fetchers/api.py` `PROVIDERS` 注册 |
| 爬虫 / 官方(爬取) | `ScraperFetcher` | ✅ 通用链接抽取已实现;反爬站点需定制解析器 |
| 邮件订阅(21) | `EmailSubscriptionFetcher` | 🔴 桩实现,需 IMAP/webhook 网关 |

## 6. 待解锁清单(按投入产出排序)

| # | 动作 | 解锁源数 | 成本 |
|---|---|---|---|
| 1 | 配置 `DATAHUB_TWITTERAPI_IO_KEY` | **262**(person 模块从 0 到有) | 一把密钥(付费) |
| 2 | fetch 前 URL 清洗(strip/百分号编码) | ~39 | 半小时代码 |
| 3 | 注册表修订 77 个 404 失效 feed | ~77 | 人工核 URL |
| 4 | 自建 RSSHub 并配 `DATAHUB_RSSHUB_BASE_URL` | ~20+(opinion 提升明显) | 一个容器 |
| 5 | GDELT 限流退避重试 | 11 | 少量代码 |
| 6 | FMP/FRED/ACLED 密钥 | 35 | 三把密钥 |
| 7 | AKShare provider 插件 | 18 | 中等(Python 库已在依赖之外) |
| 8 | 邮箱网关 | 21 | 较大(独立集成) |

## 7. 复测方法

```bash
# 全量刷新即为一次实测,统计报告落在 reports/refresh/*.md
datahub refresh

# 单源验证
datahub run --source <id>
curl -X POST http://127.0.0.1:8000/api/v1/sources/<id>/fetch

# 某源失败历史
curl "http://127.0.0.1:8000/api/v1/sources/<id>/runs?limit=5"
```

逐源明细字段说明(`reports/connectivity_report.csv`):`connectivity_class` 静态分类、
`direct_*` 直连轮结果、`proxy_*` 代理轮结果(status / items / note)。
