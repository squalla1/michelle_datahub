# Michelle DataHub — application image (API + scheduler).
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first (better layer caching). Only the project metadata
# is needed to resolve deps; the source is copied afterwards.
COPY pyproject.toml README.md ./
COPY datahub ./datahub
RUN pip install --upgrade pip && pip install ".[postgres]"

# The Excel registry is mounted at runtime; DATAHUB_DATABASE_URL must be
# injected (env_file / -e) — there is deliberately no baked-in database default.
ENV DATAHUB_CATALOG_PATH="/data/Michelle_Datasource_2026-06-02.xlsx" \
    DATAHUB_API_HOST="0.0.0.0" \
    DATAHUB_API_PORT="8000"

EXPOSE 8000

# Default: REST API + embedded scheduler. Override `command` to run the
# standalone scheduler worker (`datahub schedule`) instead.
CMD ["datahub", "serve"]
