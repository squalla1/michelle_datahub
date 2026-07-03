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

- Python 3.10+(镜像用 3.12)、PostgreSQL 14+(已在 18.3 上验证)。
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

compose 将项目 `data/` 只读挂载到容器 `/data` 提供注册表,`reports/` 读写挂载给
scheduler(刷新统计报告落在宿主机),Postgres 数据落在 `pgdata` 卷;API 服务关闭
内嵌调度器,由独立的 `scheduler` 服务负责 2 小时刷新。后续更新注册表:

```bash
docker compose run --rm ingest          # 重新解析工作簿(幂等 upsert)
docker compose restart scheduler        # worker 启动时重建任务
```

> 注意:`POST /api/v1/jobs/reload` 只重建**其所在进程内嵌调度器**的任务。此分离
> 部署中 API 设了 `DATAHUB_API_SCHEDULER=0`,该接口**不会**影响 worker —— 应重启
> `scheduler` 服务。

### 使用托管数据库(如阿里云 RDS)

完全跳过自带的 `db` 服务:把 `DATAHUB_DATABASE_URL` 指向托管实例,只启动应用服务。

```bash
export DATAHUB_DATABASE_URL="postgresql+psycopg://USER:PASS@your-instance.pgsql.japan.rds.aliyuncs.com:5432/DBNAME"
docker compose run --rm --no-deps ingest
docker compose up -d --no-deps api scheduler
```

(或直接改 `docker-compose.yml` 中 `x-app` 块的 `DATAHUB_DATABASE_URL`。)
记得把服务器出口 IP 加入 RDS 白名单。

## 5. 无 Docker 部署(systemd)

```bash
git clone <repo> /opt/datahub/app
python -m venv /opt/datahub/.venv
/opt/datahub/.venv/bin/pip install -e "/opt/datahub/app[postgres]"
cp /opt/datahub/app/.env.example /opt/datahub/.env   # 然后按 §2 编辑
```

`WorkingDirectory` 很关键:默认的 `DATAHUB_CATALOG_PATH`(`data/...`)和
`DATAHUB_REPORT_DIR`(`reports`)是相对路径,基于工作目录解析。要么保持
`WorkingDirectory=/opt/datahub/app`,要么在 `.env` 里都改成绝对路径。

两个 unit 共用一份 `EnvironmentFile=/opt/datahub/.env`:

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
Description=Michelle DataHub scheduler(各源任务 + 2h 全量刷新)
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
systemctl daemon-reload
systemctl enable --now datahub-api datahub-scheduler
```

负载均衡下多副本 API 时,调度器进程**必须只有一个**(单写者);此处的
APScheduler 是进程内存态,多个调度器会重复抓取(排重使其无害,但浪费)。

## 6. 验证

```bash
curl localhost:8000/health
curl localhost:8000/api/v1/modules                 # 9 种类型 + 源计数
curl "localhost:8000/api/v1/content/news?limit=5"  # 今天最新 5 条新闻
datahub refresh --module news                       # 立即强制抓取(排重)
```

验证调度 worker:看它的日志(`docker compose logs scheduler` /
`journalctl -u datahub-scheduler`)中的 "scheduler running. job kinds: ...",并观察
`reports/refresh/` 是否持续生成。`GET /api/v1/jobs` 只反映 API 进程**内嵌**调度器
的状态 —— 分离部署下它返回 `running: false` 是正常现象,不是故障。

## 7. 运维

- **备份:** `pg_dump`。内容可重抓恢复,但 `fetch_run` 历史与排重状态不可重建。
- **增长:** `content_item` 是热点表。数据量大时按 `fetched_at` 做月分区,和/或
  启用 `schema.sql` 中注释掉的 `ix_content_module_published` 复合索引。主键为
  `SERIAL`(int32),接近 ~21 亿行前应改为 `BIGINT IDENTITY`。
- **监控:** 最快的信号是每轮刷新的统计报告 `reports/refresh/*.md`
  (`DATAHUB_REPORT_DIR`)—— 每轮的 ok/error/skipped + 各模块新增条数。告警建议
  直接查 SQL:`fetch_run` 的新鲜度与错误率(如 `select max(started_at) from
  fetch_run` 应始终落在刷新周期内)。约 30% 的在线源存在瞬时失败
  (404/403/SSL/限流)—— 关注趋势而非单点失败。`GET /api/v1/jobs` 仅在 API 内嵌
  调度器时(`DATAHUB_API_SCHEDULER=1`)有意义。
- **驱动注意:** URL scheme 必须是 `postgresql+psycopg://`(psycopg 3,来自
  `[postgres]` extra),**不是** `postgresql://`(默认走 psycopg2)。
