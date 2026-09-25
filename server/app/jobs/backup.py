"""Backup jobs, plus the loop that decides when a scheduled one is due.

The loop runs as a thread inside the worker process (see app.worker_main): the
worker is the only container with write access to /backups, and unlike the
server it is not restarted every time a source file changes.

That thread deliberately does no database work. RQ forks a child per job, and a
child inherits the parent's connection pool -- so a connection opened in the
parent (on a loop that is long gone by then) makes every forked job fail with
"attached to a different loop". The thread only ever talks to Redis; whether a
backup is actually due is decided inside the job, where the fork already
happened and a fresh pool is safe.
"""
import asyncio
import time
from datetime import datetime, timedelta, timezone

from rq.registry import StartedJobRegistry

from app.db import async_session
from app.models.settings import AppSettings
from app.queue import DEFAULT_RETRY, job_queue
from app.services import backup

CHECK_INTERVAL_SECONDS = 1800
INTERVALS = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}


def run_scheduled_db_backup(source: str = "scheduled") -> dict:
    return asyncio.run(_run_db_backup(source))


async def _run_db_backup(source: str) -> dict:
    async with async_session() as db:
        row = await db.get(AppSettings, 1)
        keep = row.backup_keep if row else 7
        if source == "scheduled":
            if not (row and row.backup_enabled):
                return {"skipped": "backups are disabled"}
            if not _is_due(row.backup_frequency):
                return {"skipped": "not due yet"}
    return backup.run_db_backup(keep, source=source)


def _is_due(frequency: str) -> bool:
    last = backup.last_success_at("db")
    return last is None or datetime.now(timezone.utc) - last >= INTERVALS[frequency]


def run_media_backup_job() -> dict:
    return asyncio.run(_run_media_backup())


async def _run_media_backup() -> dict:
    async with async_session() as db:
        row = await db.get(AppSettings, 1)
        keep = row.backup_keep if row else 7
    return backup.run_media_backup(keep)


def _backup_already_pending() -> bool:
    """Redis only -- see the module docstring for why this must not hit the DB."""
    ids = list(job_queue.get_job_ids()) + list(StartedJobRegistry(queue=job_queue).get_job_ids())
    return any(
        (job := job_queue.fetch_job(job_id)) and (job.func_name or "").endswith("run_scheduled_db_backup")
        for job_id in ids
    )


def scheduler_loop() -> None:
    while True:
        try:
            if not _backup_already_pending():
                job_queue.enqueue(run_scheduled_db_backup, retry=DEFAULT_RETRY)
        except Exception as exc:  # noqa: BLE001 -- the schedule must never take the worker down
            print(f"backup scheduler: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(CHECK_INTERVAL_SECONDS)
