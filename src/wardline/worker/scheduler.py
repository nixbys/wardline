"""Periodic connector triggers (report 4.1 'connectors on schedules').

Registration is deliberately empty at import time — connectors register their
own periodic jobs (if any) via `register_periodic()` when the registry loads
them, so this module never needs to know connector names.
"""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from wardline.common.logging import get_logger

logger = get_logger(__name__)

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
    return _scheduler


def register_periodic(job_id: str, func, seconds: int) -> None:
    get_scheduler().add_job(func, "interval", seconds=seconds, id=job_id, replace_existing=True)


def start_scheduler() -> None:
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("scheduler.started")
