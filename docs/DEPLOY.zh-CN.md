# 部署指南

> **语言:** [English](DEPLOY.md) | 中文

**Michelle DataHub**(目录驱动数据引擎 + REST API)基于 **PostgreSQL** 的打包与
部署说明。

系统由两个常驻进程和一次性初始化步骤组成:

| 进程 | 命令 | 角色 |
|---|---|---|
| API | `datahub serve` | FastAPI,监听 `:8000`(`/docs`、`/api/v1/...`) |
| 调度器 | `datahub schedule` | 各源`频率`任务 + 全局 2 小时刷新 |
| 初始化(一次) | `datahub init-db && datahub ingest` | 建表 + 载入 Excel 注册表 |

小规模部署可以单进程兼任(`serve` 内嵌调度器)。正式环境应将 API 与调度器
**分开运行**,API 重启不影响抓取 —— API 侧设置 `DATAHUB_API_SCHEDULER=0`。

---

## 1. 前置条件

- Python 3.10+(镜像用 3.12)、PostgreSQL 14+。
- Excel 注册表文件(`data/Michelle_Datasource_*.xlsx`)可通过
  `DATAHUB_CATALOG_PATH` 访问。

## 2. 配置

所有配置来自 `DATAHUB_*` 环境变量(或 `.env`),见 `.env.example`。
部署关键项:

| 变量 | 示例 | 说明 |
|---|---|---|
| `DATAHUB_DATABASE_URL` | `postgresql+psycopg://datahub:pw@db:5432/datahub` | **必须**使用 `+psycopg`(psycopg 3)驱动 |
| `DATAHUB_CATALOG_PATH` | `/data/Michelle_Datasource_2026-06-02.xlsx` | 注册表路径 |
| `DATAHUB_API_SCHEDULER` | API 进程设 `0` | `0` = 不内嵌调度器 |
| `DATAHUB_REFRESH_ALL_HOURS` | `2` | 全量刷新周期;`0` 关闭 |
| `DATAHUB_RSSHUB_BASE_URL` | `https://your-rsshub` | 建议自建 RSSHub;公共实例不稳定 |
| `DATAHUB_*_API_KEY` | — | 可选 provider 密钥(FMP/FRED/twitterapi.io/ACLED) |

## 3. 数据库准备(PostgreSQL)

创建库和角色后,用**两种等价方式之一**建 schema:

```bash
# 角色 + 数据库
createdb datahub && createuser datahub --pwprompt   # 或用托管 PG 的控制台

# (a) DBA 管理 —— 应用权威 DDL
psql "$DATAHUB_DATABASE_URL" -f deploy/schema.sql

# (b) 应用管理 —— 由 SQLAlchemy create_all 建表
datahub init-db
```

两种方式产出**完全一致**的 schema(`deploy/schema.sql` 与 `datahub/models/` 的
ORM 保持字节级对齐:`SERIAL` 主键、`JSONB` payload、UTC `TIMESTAMP`、
`uq_source(module,name,url)` / `uq_content(source_id,external_id)` 排重键及全部
索引)。权威定义见 [`deploy/schema.sql`](../deploy/schema.sql)。随后载入注册表:

```bash
datahub ingest        # 解析 Excel 工作簿写入 data_source(幂等)
```

### Schema 概览

```
data_source ──1:N──> fetch_run     (每次抓取的审计记录)
     │
     └────────1:N──> content_item  (抓取内容;按 source_id+external_id 排重)
```

`content_item.payload` 与 `data_source.extra` 为 `JSONB`;时间戳均为 UTC。
按类型接口(`GET /api/v1/content/{module}`)按 `published_at` / `fetched_at`
过滤 —— 两列均有索引。

## 4. Docker Compose 部署(推荐)

产物在 `deploy/`(`Dockerfile`、`docker-compose.yml`)。

```bash
cd deploy
export POSTGRES_PASSWORD=change-me

docker compose up -d db                 # 1. PostgreSQL(带健康检查)
docker compose run --rm ingest          # 2. 建 schema + 载入注册表(一次)
docker compose up -d api scheduler      # 3. API(:8000)+ 调度器 worker
```

compose 将项目 `data/` 只读挂载到容器 `/data` 提供注册表,Postgres 数据落在
`pgdata` 卷;API 服务关闭内嵌调度器,由独立的 `scheduler` 服务负责 2 小时刷新。
后续更新注册表可不停机:

```bash
docker compose run --rm ingest
curl -X POST localhost:8000/api/v1/jobs/reload    # 重建调度任务
```

## 5. 无 Docker 部署(systemd)

```bash
python -m venv /opt/datahub/.venv
/opt/datahub/.venv/bin/pip install ".[postgres]"
```

两个 unit 共用一份 `EnvironmentFile=/opt/datahub/.env`:

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

负载均衡下多副本 API 时,调度器进程**必须只有一个**(单写者);此处的
APScheduler 是进程内存态,多个调度器会重复抓取(排重使其无害,但浪费)。

## 6. 验证

```bash
curl localhost:8000/health
curl localhost:8000/api/v1/modules                 # 9 种类型 + 源计数
curl "localhost:8000/api/v1/content/news?limit=5"  # 今天最新 5 条新闻
curl localhost:8000/api/v1/jobs                     # 调度状态(含 refresh-all)
datahub refresh --module news                       # 立即强制抓取(排重)
```

## 7. 运维

- **备份:** `pg_dump`。内容可重抓恢复,但 `fetch_run` 历史与排重状态不可重建。
- **增长:** `content_item` 是热点表。数据量大时按 `fetched_at` 做月分区,和/或
  启用 `schema.sql` 中注释掉的 `ix_content_module_published` 复合索引。主键为
  `SERIAL`(int32),接近 ~21 亿行前应改为 `BIGINT IDENTITY`。
- **监控:** 轮询 `GET /api/v1/jobs`;对 `fetch_run.status='error'` 比例告警。
  约 30% 的在线源存在瞬时失败(404/403/SSL/限流)—— 关注趋势而非单点失败。
- **驱动注意:** URL scheme 必须是 `postgresql+psycopg://`(psycopg 3,来自
  `[postgres]` extra),**不是** `postgresql://`(默认走 psycopg2)。
