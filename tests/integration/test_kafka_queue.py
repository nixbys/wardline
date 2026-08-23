"""Integration test for the real Kafka job-dispatch backend
(worker/kafka_queue.py) -- the noted upgrade path from the Postgres SKIP
LOCKED queue (see the README's scope-reductions table and worker/jobs.py's
own docstring on why that queue is a real substitute for a Kafka consumer
group's guarantee at this scale).

Requires a real Kafka reachable at KAFKA_BOOTSTRAP_SERVERS; CI provisions
one as a service container. Skips itself otherwise, same as the other
tests in this directory.
"""

from __future__ import annotations

import os
import uuid

import pytest

KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
pytestmark = pytest.mark.skipif(
    not KAFKA_BOOTSTRAP_SERVERS, reason="KAFKA_BOOTSTRAP_SERVERS not set -- no live Kafka to test against"
)


@pytest.fixture
def kafka_topic(monkeypatch):
    """Points kafka_queue at a throwaway topic for this test only."""
    from wardline.common.config import get_settings
    from wardline.worker import kafka_queue

    topic = f"wardline-test-jobs-{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("KAFKA_INGESTION_TOPIC", topic)
    get_settings.cache_clear()
    kafka_queue._producer.cache_clear()

    yield topic

    get_settings.cache_clear()
    kafka_queue._producer.cache_clear()


def test_publish_and_consume_one_job(kafka_topic):
    from wardline.worker.kafka_queue import consume_forever, publish_job

    publish_job("job_abc123", "wikipedia", {"search": "Acme Corp"})

    received = []

    def handler(job_id, connector_name, params):
        received.append((job_id, connector_name, params))
        raise _StopConsuming

    with pytest.raises(_StopConsuming):
        consume_forever(handler)

    assert received == [("job_abc123", "wikipedia", {"search": "Acme Corp"})]


class _StopConsuming(BaseException):
    """Breaks consume_forever's `while True` after the first message --
    it has no other exit condition by design (a real worker runs it
    forever), so the test has to end the loop itself. Inherits from
    BaseException, not Exception: consume_forever deliberately catches
    plain Exception around the handler call (so a bad message can't kill
    a real worker), which would otherwise swallow this too.
    """
