"""Kafka-backed job dispatch (`settings.job_queue_backend == "kafka"`) --
the real version of the "Kafka consumer-group guarantee" `worker/jobs.py`'s
own docstring notes the Postgres `SELECT ... FOR UPDATE SKIP LOCKED` queue
substitutes for. Postgres stays the default: a handful of slow-moving
connectors don't need a streaming bus.

The `IngestionJob` row (`api/routers/admin_connectors.py`) is still
created either way -- it's this app's audit trail and job-status API
(`GET /v1/admin/connectors/jobs/{job_id}`), not just a work queue. Kafka
here is purely the dispatch mechanism telling a worker "a job is ready";
`worker/jobs.py::claim_job_by_id` still does the actual state transition,
with its own row-level lock as a second guard against ever double-running
one job (a redelivered message after a crash-before-commit should be a
no-op, not a duplicate run).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import lru_cache

from wardline.common.config import get_settings
from wardline.common.logging import get_logger

logger = get_logger(__name__)


@lru_cache
def _producer():
    from confluent_kafka import Producer

    return Producer({"bootstrap.servers": get_settings().kafka_bootstrap_servers})


def publish_job(job_id: str, connector_name: str, params: dict) -> None:
    producer = _producer()
    payload = json.dumps(
        {"job_id": job_id, "connector_name": connector_name, "params": params}
    ).encode("utf-8")
    producer.produce(get_settings().kafka_ingestion_topic, payload)
    producer.flush(10)
    logger.info("kafka_queue.published", job_id=job_id, connector=connector_name)


def consume_forever(handler: Callable[[str, str, dict], None]) -> None:
    """Blocks forever, calling `handler(job_id, connector_name, params)` for
    each message. The consumer group (`group.id` below) is what gives
    multiple worker replicas the same "exactly one of you handles this"
    guarantee `worker/jobs.py`'s SKIP LOCKED path achieves without Kafka.
    Offsets commit only after `handler` returns, so a crash mid-job gets
    the message redelivered rather than silently dropped -- at-least-once,
    matching the Postgres path's own semantics (a job stuck "running" from
    a dead worker isn't auto-retried there either; this is no weaker).
    """
    from confluent_kafka import Consumer

    settings = get_settings()
    consumer = Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": "wardline-worker",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([settings.kafka_ingestion_topic])
    logger.info("kafka_queue.consuming", topic=settings.kafka_ingestion_topic)
    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                logger.error("kafka_queue.poll_error", error=str(msg.error()))
                continue
            try:
                payload = json.loads(msg.value())
                handler(payload["job_id"], payload["connector_name"], payload["params"])
            except Exception as exc:  # a bad/unparseable message must not kill the consumer
                logger.error("kafka_queue.handler_failed", error=str(exc))
            consumer.commit(msg)
    finally:
        consumer.close()
