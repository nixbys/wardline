"""Ingestion job-queue worker: polls `ingestion_jobs` with SKIP LOCKED and runs
the matching connector's discover->fetch->parse->ingest pipeline. This
substitutes for Airflow at single-node scale (documented scope reduction
in the plan) -- and, when `settings.job_queue_backend == "postgres"`
(the default), for Kafka's dispatch role too. Set it to "kafka" to consume
from a real topic instead (see worker/kafka_queue.py); the IngestionJob
row and run_job() pipeline are identical either way.
"""

from __future__ import annotations

import time

from wardline.common.config import get_settings
from wardline.common.logging import configure_logging, get_logger
from wardline.worker.scheduler import register_periodic, start_scheduler

logger = get_logger(__name__)

POLL_INTERVAL_SECONDS = 2.0


def run_forever() -> None:
    settings = get_settings()
    configure_logging(settings.environment)
    logger.info("worker.startup")

    if settings.entity_resolution_batch_enabled:
        from wardline.graph.entity_resolution.splink_batch import run_scheduled_batch_resolution

        register_periodic(
            "entity-resolution-batch",
            run_scheduled_batch_resolution,
            settings.entity_resolution_batch_interval_seconds,
        )
    if settings.iceberg_export_enabled:
        from wardline.storage.iceberg_export import export_audit_events

        register_periodic(
            "iceberg-audit-export",
            export_audit_events,
            settings.iceberg_export_interval_seconds,
        )
    start_scheduler()

    from wardline.worker.jobs import claim_job_by_id, claim_next_job, run_job

    if settings.job_queue_backend == "kafka":
        from wardline.worker.kafka_queue import consume_forever

        def _handle(job_id: str, _connector_name: str, _params: dict) -> None:
            # connector_name/params are already on the IngestionJob row
            # itself (created by the API route before publishing); run_job
            # reads them from there, not from the Kafka message.
            job = claim_job_by_id(job_id)
            if job is not None:
                run_job(job)

        consume_forever(_handle)
        return

    while True:
        job = claim_next_job()
        if job is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        run_job(job)


if __name__ == "__main__":
    run_forever()
