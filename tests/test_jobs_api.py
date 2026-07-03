"""Jobs endpoints must not 500 when the API runs without the embedded scheduler
(split deployment: jobs exist in the scheduler object but it is not started)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from datahub.api.app import create_app


def test_jobs_endpoints_with_scheduler_stopped(clean_db):
    c = TestClient(create_app())

    r = c.get("/api/v1/jobs")
    assert r.status_code == 200
    assert r.json()["running"] is False

    # reload adds jobs to the non-running scheduler; must still serialize them
    r = c.post("/api/v1/jobs/reload")
    assert r.status_code == 200
    body = r.json()
    assert body["reloaded"] is True and "refresh" in body["by_kind"]

    r = c.get("/api/v1/jobs")
    assert r.status_code == 200
