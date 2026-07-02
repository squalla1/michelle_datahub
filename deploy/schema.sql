-- =============================================================================
-- Michelle DataHub — PostgreSQL schema (canonical DDL)
-- =============================================================================
-- This mirrors the SQLAlchemy ORM in datahub/models/__init__.py exactly, so a
-- DBA-managed database and `datahub init-db` (create_all) produce the same
-- shape. Apply with:  psql "$DATAHUB_DATABASE_URL" -f deploy/schema.sql
--
-- Conventions:
--   * All timestamps are UTC, stored as TIMESTAMP (without time zone) — the app
--     normalizes every datetime to UTC before persisting.
--   * JSON columns are JSONB (indexable, compact).
--   * Unique constraints treat NULL as distinct (Postgres default); the catalog
--     ingest de-dups rows in application code, so this is intentional.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- data_source — one row of the Excel registry, normalized.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS data_source (
    id           SERIAL        PRIMARY KEY,
    module       VARCHAR(32)   NOT NULL,
    tab          VARCHAR(64)   NOT NULL,
    l1_category  VARCHAR(128),
    l2_category  VARCHAR(128),
    name         VARCHAR(256)  NOT NULL,
    url          TEXT,
    method       VARCHAR(64),
    paid         VARCHAR(64),
    account      VARCHAR(128),
    frequency    VARCHAR(64),
    remark       TEXT,
    priority     VARCHAR(8),
    health       VARCHAR(8),
    extra        JSONB         NOT NULL DEFAULT '{}'::jsonb,
    enabled      BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMP     NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    CONSTRAINT uq_source UNIQUE (module, name, url)
);

CREATE INDEX IF NOT EXISTS ix_data_source_module   ON data_source (module);
CREATE INDEX IF NOT EXISTS ix_data_source_name     ON data_source (name);
CREATE INDEX IF NOT EXISTS ix_data_source_method   ON data_source (method);
CREATE INDEX IF NOT EXISTS ix_data_source_priority ON data_source (priority);
CREATE INDEX IF NOT EXISTS ix_data_source_enabled  ON data_source (enabled);

-- ---------------------------------------------------------------------------
-- fetch_run — audit record for one fetch execution against a source.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fetch_run (
    id           SERIAL       PRIMARY KEY,
    source_id    INTEGER      NOT NULL REFERENCES data_source (id) ON DELETE CASCADE,
    started_at   TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    finished_at  TIMESTAMP,
    status       VARCHAR(16)  NOT NULL DEFAULT 'running',  -- ok / error / skipped / running
    item_count   INTEGER      NOT NULL DEFAULT 0,
    new_count    INTEGER      NOT NULL DEFAULT 0,
    error        TEXT
);

CREATE INDEX IF NOT EXISTS ix_fetch_run_source_id ON fetch_run (source_id);

-- ---------------------------------------------------------------------------
-- content_item — a fetched item. Common fields normalized; module-specific
-- fields in the JSONB payload. Dedup key is (source_id, external_id).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS content_item (
    id            SERIAL        PRIMARY KEY,
    source_id     INTEGER       NOT NULL REFERENCES data_source (id) ON DELETE CASCADE,
    module        VARCHAR(32)   NOT NULL,
    external_id   VARCHAR(512)  NOT NULL,
    title         TEXT,
    url           TEXT,
    summary       TEXT,
    published_at  TIMESTAMP,
    payload       JSONB         NOT NULL DEFAULT '{}'::jsonb,
    fetched_at    TIMESTAMP     NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    CONSTRAINT uq_content UNIQUE (source_id, external_id)
);

CREATE INDEX IF NOT EXISTS ix_content_item_source_id    ON content_item (source_id);
CREATE INDEX IF NOT EXISTS ix_content_item_module       ON content_item (module);
CREATE INDEX IF NOT EXISTS ix_content_item_published_at ON content_item (published_at);
CREATE INDEX IF NOT EXISTS ix_content_item_fetched_at   ON content_item (fetched_at);

-- Optional: speeds up the per-type "today's latest N" endpoint
-- (GET /api/v1/content/{module}?date=...). Uncomment if that path is hot.
-- CREATE INDEX IF NOT EXISTS ix_content_module_published
--     ON content_item (module, published_at DESC);

COMMIT;
