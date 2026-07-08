"""Ingestion job-queue worker: polls `ingestion_jobs` with SKIP LOCKED and runs
the matching connector's discover->fetch->parse->ingest pipeline. This
substitutes for Kafka/Airflow at single-node scale (documented scope
reduction in the plan).
"""

from __future__ import annotations

import time

from cranus.common.config import get_settings
from cranus.common.logging import configure_logging, get_logger
from cranus.worker.scheduler import start_scheduler

logger = get_logger(__name__)

POLL_INTERVAL_SECONDS = 2.0


def run_forever() -> None:
    settings = get_settings()
    configure_logging(settings.environment)
    logger.info("worker.startup")
    start_scheduler()

    from cranus.worker.jobs import claim_next_job, run_job

    while True:
        job = claim_next_job()
        if job is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        run_job(job)


if __name__ == "__main__":
    run_forever()
