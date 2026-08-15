"""Command-line entrypoint.

    datahub init-db                 create database tables
    datahub ingest [--path FILE]    parse the Excel registry into the catalog
    datahub list [--module m]       list catalog sources
    datahub run --source ID         fetch one source now
    datahub run --module m [--limit N]   fetch sources of a module now
    datahub refresh [--module m]    fetch ALL enabled sources once (dedup)
    datahub enrich [--limit N]      extract article fulltext for stored items
    datahub purge [--days N]        delete content older than the retention window
    datahub serve                   run the REST API (uvicorn)
    datahub schedule                run the scheduler in the foreground
"""

from __future__ import annotations

import argparse
import logging
import time

from .config import get_settings
from .ingest import (
    enrich_fulltext,
    enrich_images,
    ingest_catalog,
    purge_old_content,
    run_all_sources,
    run_source,
)
from .storage import init_db, session_scope

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def _cmd_init_db(_args) -> None:
    init_db()
    print("database initialized")


def _cmd_ingest(args) -> None:
    init_db()
    summary = ingest_catalog(args.path)
    print(f"catalog ingested: {summary}")


def _cmd_list(args) -> None:
    from sqlalchemy import select

    from .models import DataSource

    with session_scope() as session:
        stmt = select(DataSource)
        if args.module:
            stmt = stmt.where(DataSource.module == args.module)
        stmt = stmt.limit(args.limit)
        for s in session.scalars(stmt):
            print(f"[{s.id}] {s.module:8} {s.priority or '--':3} {s.method or '?':18} {s.name}")


def _cmd_run(args) -> None:
    init_db()
    if args.source:
        print(run_source(args.source))
        return

    from sqlalchemy import select

    from .models import DataSource

    with session_scope() as session:
        stmt = select(DataSource.id).where(DataSource.enabled.is_(True))
        if args.module:
            stmt = stmt.where(DataSource.module == args.module)
        if args.priority:
            stmt = stmt.where(DataSource.priority == args.priority)
        ids = list(session.scalars(stmt.limit(args.limit)))
    for sid in ids:
        print(run_source(sid))


def _cmd_refresh(args) -> None:
    init_db()
    print(run_all_sources(module=args.module))


def _cmd_enrich(args) -> None:
    init_db()
    print(enrich_fulltext(limit=args.limit, module=args.module))
    print(enrich_images(limit=args.limit, module=args.module))


def _cmd_purge(args) -> None:
    init_db()
    print(purge_old_content(days=args.days))


def _cmd_serve(_args) -> None:
    import uvicorn

    s = get_settings()
    uvicorn.run("datahub.api.app:app", host=s.api_host, port=s.api_port, factory=False)


def _cmd_schedule(_args) -> None:
    init_db()
    from .scheduler import scheduler_service

    counts = scheduler_service.load_jobs()
    scheduler_service.start()
    print(f"scheduler running. job kinds: {counts}")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        scheduler_service.shutdown()
        print("scheduler stopped")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="datahub", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db").set_defaults(func=_cmd_init_db)

    pi = sub.add_parser("ingest")
    pi.add_argument("--path", default=None, help="path to the Excel registry")
    pi.set_defaults(func=_cmd_ingest)

    pl = sub.add_parser("list")
    pl.add_argument("--module")
    pl.add_argument("--limit", type=int, default=50)
    pl.set_defaults(func=_cmd_list)

    pr = sub.add_parser("run")
    pr.add_argument("--source", type=int, help="source id")
    pr.add_argument("--module")
    pr.add_argument("--priority")
    pr.add_argument("--limit", type=int, default=20)
    pr.set_defaults(func=_cmd_run)

    prf = sub.add_parser("refresh", help="fetch ALL enabled sources once (dedup)")
    prf.add_argument("--module", help="limit the refresh to one module")
    prf.set_defaults(func=_cmd_refresh)

    pe = sub.add_parser("enrich", help="extract article fulltext for stored items")
    pe.add_argument("--limit", type=int, default=None, help="items per run (default: config)")
    pe.add_argument("--module", help="limit to one module")
    pe.set_defaults(func=_cmd_enrich)

    pp = sub.add_parser("purge", help="delete content older than the retention window")
    pp.add_argument("--days", type=int, default=None, help="override retention_days")
    pp.set_defaults(func=_cmd_purge)

    sub.add_parser("serve").set_defaults(func=_cmd_serve)
    sub.add_parser("schedule").set_defaults(func=_cmd_schedule)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
