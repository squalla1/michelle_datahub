# 部署指南

> **语言:** [English](DEPLOY.md) | 中文

数据库使用**托管 PostgreSQL**(阿里云 RDS,已在 18.3 验证),不自建。
两个常驻进程,一次性初始化:

| 进程 | 命令 | 说明 |
|---|---|---|
| API | `datahub serve` | REST 接口 `:8000`(需设 `DATAHUB_API_SCHEDULER=0`) |
| 调度器 | `datahub schedule` | 各源定时任务 + 每 2 小时全量刷新 |
| 初始化(一次) | `datahub init-db && datahub ingest` | 建表 + 载入注册表(均幂等) |

## 1. 配置

项目根目录 `.env`(模板:`.env.example`)。**数据库连接只配这一处**:

```bash
DATAHUB_DATABASE_URL=postgresql+psycopg://USER:PASS@<RDS地址>:5432/<库名>
```

- 前缀必须是 `postgresql+psycopg://`(psycopg 3,装 `pip install ".[postgres]"`);
  写 `postgresql://` 会报错。
- 服务器出口 IP 必须加入 RDS 白名单。

其他按需:

| 变量 | 默认 | 说明 |
|---|---|---|
| `DATAHUB_CATALOG_PATH` | `data/….xlsx` | 注册表路径(相对工作目录) |
| `DATAHUB_REPORT_DIR` | `reports` | 每轮刷新的统计报告目录 |
| `DATAHUB_REFRESH_ALL_HOURS` | `2` | 全量刷新周期;`0` 关闭 |
| `DATAHUB_RSSHUB_BASE_URL` | 公共实例(不可用) | 自建 RSSHub 地址 |
| `DATAHUB_*_API_KEY` | 空 | provider 密钥(twitterapi.io/FMP/FRED/ACLED) |

## 2. 方式 A:Docker Compose

```bash
cp .env.example .env && vi .env       # 设 DATAHUB_DATABASE_URL
cd deploy
docker compose run --rm ingest        # 一次:建表 + 载入注册表
docker compose up -d api scheduler
```

注册表(Excel)更新后:

```bash
docker compose run --rm ingest && docker compose restart scheduler
```

> `POST /api/v1/jobs/reload` 只作用于 API 进程内嵌调度器,分离部署下**对 worker 无效**,不要用它。

## 3. 方式 B:systemd

```bash
git clone <repo> /opt/datahub/app
python -m venv /opt/datahub/.venv
/opt/datahub/.venv/bin/pip install -e "/opt/datahub/app[postgres]"
cp /opt/datahub/app/.env.example /opt/datahub/.env   # 编辑,见 §1
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

注意:`DATAHUB_CATALOG_PATH`、`DATAHUB_REPORT_DIR` 默认是相对路径,基于
`WorkingDirectory` 解析 —— 保持上面的配置即可,或在 `.env` 改为绝对路径。

## 4. 验证

```bash
curl localhost:8000/health
curl "localhost:8000/api/v1/content/news?limit=5"
journalctl -u datahub-scheduler | grep "scheduler running"   # 或 docker compose logs scheduler
ls reports/refresh/          # 每轮刷新生成一份统计报告
```

分离部署下 `GET /api/v1/jobs` 返回 `running: false` 是正常现象(它反映的是 API
进程,不是 worker)。

## 5. 运维

- **看结果**:`reports/refresh/*.md`(每轮 ok/error/skipped + 各模块新增)。
- **告警**:`select max(started_at) from fetch_run` 应落在刷新周期内;error 率看
  趋势(约 30% 在线源存在瞬时失败属正常)。
- **备份**:`pg_dump`;内容可重抓,`fetch_run` 历史与排重状态不可重建。
- **建表参考**:`deploy/schema.sql` 是权威 DDL,与 `datahub init-db` 产出一致,
  DBA 可直接 `psql -f` 执行。
