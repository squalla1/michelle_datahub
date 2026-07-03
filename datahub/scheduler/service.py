"""Build and run scheduled fetch jobs from the catalog.

One APScheduler job per schedulable, enabled source. The trigger is derived from
the source's `频率` via parse_frequency. Realtime/interval jobs are jittered to
avoid thundering-herd polling."""

from __future__ import annotations

import logging
import random

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from ..config import get_settings
from ..ingest.enrich import enrich_fulltext
from ..ingest.retention import purge_old_content
from ..ingest.runner import run_all_sources, run_source
from ..models import DataSource
from ..storage import session_scope
from .frequency import parse_frequency

logger = logging.getLogger("datahub.scheduler")

REFRESH_JOB_ID = "refresh-all"
ENRICH_JOB_ID = "fulltext-enrich"
PURGE_JOB_ID = "retention-purge"


def _job(source_id: int) -> None:
    try:
        summary = run_source(source_id)
        logger.info("fetched source=%s -> %s", source_id, summary)
    except Exception:  # never let a job kill the scheduler thread
        logger.exception("fetch job failed for source=%s", source_id)


def _refresh_all_job() -> None:
    try:
        summary = run_all_sources()
        logger.info("global refresh -> %s", summary)
    except Exception:  # never let the sweep kill the scheduler thread
        logger.exception("global refresh job failed")


def _enrich_job() -> None:
    try:
        enrich_fulltext()
    except Exception:
        logger.exception("fulltext enrich job failed")


def _purge_job() -> None:
    try:
        purge_old_content()
    except Exception:
        logger.exception("retention purge job failed")


class SchedulerService:
    def __init__(self) -> None:
        self.scheduler = BackgroundScheduler()

    def load_jobs(self) -> dict:
        """(Re)build the job table from the catalog. Returns a counts summary."""
        counts = {"interval": 0, "cron": 0, "manual": 0, "refresh": 0}
        counts["refresh"] = self._load_refresh_job()
        counts["enrich"] = self._load_enrich_job()
        counts["purge"] = self._load_purge_job()
        with session_scope() as session:
            sources = session.scalars(
                select(DataSource).where(DataSource.enabled.is_(True))
            ).all()
            for src in sources:
                spec = parse_frequency(src.frequency)
                counts[spec.kind] = counts.get(spec.kind, 0) + 1
                if not spec.schedulable:
                    continue
                job_id = f"src-{src.id}"
                if spec.kind == "interval":
                    trigger = IntervalTrigger(
                        seconds=spec.seconds,
                        jitter=min(spec.seconds // 2, 60) if spec.seconds else 0,
                    )
                else:
                    trigger = CronTrigger(**spec.cron)
                self.scheduler.add_job(
                    _job,
                    trigger=trigger,
                    id=job_id,
                    args=[src.id],
                    replace_existing=True,
                    next_run_time=None,
                    misfire_grace_time=300,
                    coalesce=True,
                    max_instances=1,
                )
        return counts

    def _load_refresh_job(self) -> int:
        """Add the global every-N-hours refresh of all enabled sources.

        Returns 1 if scheduled, 0 if disabled (refresh_all_hours <= 0)."""
        hours = get_settings().refresh_all_hours
        if not hours or hours <= 0:
            self.scheduler.remove_job(REFRESH_JOB_ID) if self.scheduler.get_job(
                REFRESH_JOB_ID
            ) else None
            return 0
        self.scheduler.add_job(
            _refresh_all_job,
            trigger=CronTrigger(hour=f"*/{hours}", minute=0),
            id=REFRESH_JOB_ID,
            replace_existing=True,
            misfire_grace_time=600,
            coalesce=True,
            max_instances=1,
        )
        return 1

    def _load_enrich_job(self) -> int:
        """Fulltext enrichment every fulltext_interval_minutes (0/disabled -> off)."""
        s = get_settings()
        if not s.fulltext_enabled or s.fulltext_interval_minutes <= 0:
            if self.scheduler.get_job(ENRICH_JOB_ID):
                self.scheduler.remove_job(ENRICH_JOB_ID)
            return 0
        self.scheduler.add_job(
            _enrich_job,
            trigger=IntervalTrigger(minutes=s.fulltext_interval_minutes),
            id=ENRICH_JOB_ID,
            replace_existing=True,
            misfire_grace_time=300,
            coalesce=True,
            max_instances=1,
        )
        return 1

    def _load_purge_job(self) -> int:
        """Daily retention purge at 04:30 UTC (retention_days <= 0 -> off)."""
        if get_settings().retention_days <= 0:
            if self.scheduler.get_job(PURGE_JOB_ID):
                self.scheduler.remove_job(PURGE_JOB_ID)
            return 0
        self.scheduler.add_job(
            _purge_job,
            trigger=CronTrigger(hour=4, minute=30),
            id=PURGE_JOB_ID,
            replace_existing=True,
            misfire_grace_time=3600,
            coalesce=True,
            max_instances=1,
        )
        return 1

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("scheduler started with %d jobs", len(self.scheduler.get_jobs()))

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def jobs(self) -> list[dict]:
        out = []
        for j in self.scheduler.get_jobs():
            # Jobs added while the scheduler is not running (e.g. the API process
            # in split deployments) have no next_run_time attribute yet.
            nrt = getattr(j, "next_run_time", None)
            out.append(
                {
                    "id": j.id,
                    "next_run_time": nrt.isoformat() if nrt else None,
                    "trigger": str(j.trigger),
                }
            )
        return out


# Module-level singleton reused by the API process.
scheduler_service = SchedulerService()
