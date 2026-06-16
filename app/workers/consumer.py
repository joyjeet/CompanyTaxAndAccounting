"""Redis Streams consumer loop.

Runs `dispatch_payload` for each delivered job, with at-least-once delivery,
retries on transient failure, and a dead-letter stream after `MAX_DELIVERIES`.

This entrypoint is what a worker container's CMD runs. It is intentionally
small — all real logic lives in `app.workers.jobs.dispatch_payload`, which is
unit-tested without Redis.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import socket
import time
from typing import Any

import redis

from app.core.config import get_settings
from app.workers.jobs import dispatch_payload

logger = logging.getLogger(__name__)

DEFAULT_QUEUES = ("extract", "classify")
GROUP = "ctaa"
DEAD_LETTER_STREAM = "jobs:dead"
MAX_DELIVERIES = 5
BACKOFF_BASE_SECONDS = 1.0
POLL_BLOCK_MS = 5_000


_should_stop = False


def _handle_signal(signum: int, frame: Any) -> None:  # noqa: ANN401
    global _should_stop
    logger.info("received signal %s; shutting down after current job", signum)
    _should_stop = True


def _ensure_groups(r: redis.Redis, queues: list[str]) -> None:
    for q in queues:
        stream = f"jobs:{q}"
        try:
            r.xgroup_create(name=stream, groupname=GROUP, id="$", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                continue
            raise


def _dead_letter(r: redis.Redis, *, stream: str, msg_id: str, payload: dict[str, Any], reason: str) -> None:
    r.xadd(
        DEAD_LETTER_STREAM,
        {
            "source_stream": stream,
            "source_id": msg_id,
            "payload": json.dumps(payload, default=str),
            "reason": reason,
        },
    )


def _process(r: redis.Redis, stream: str, msg_id: str, fields: dict[str, str]) -> None:
    payload_raw = fields.get("payload", "{}")
    payload = json.loads(payload_raw)
    deliveries = int(fields.get("deliveries", 1))

    try:
        dispatch_payload(payload)
        r.xack(stream, GROUP, msg_id)
    except Exception as e:
        logger.exception("job %s on %s failed (delivery %d): %s", msg_id, stream, deliveries, e)
        if deliveries >= MAX_DELIVERIES:
            _dead_letter(
                r,
                stream=stream,
                msg_id=msg_id,
                payload=payload,
                reason=f"{type(e).__name__}: {e}",
            )
            r.xack(stream, GROUP, msg_id)  # don't keep redelivering
            return
        # Re-queue with incremented delivery count and exponential backoff.
        time.sleep(BACKOFF_BASE_SECONDS * (2 ** (deliveries - 1)))
        r.xadd(
            stream,
            {"payload": payload_raw, "deliveries": str(deliveries + 1)},
        )
        r.xack(stream, GROUP, msg_id)


def run(queue_names: list[str] | None = None, *, consumer_name: str | None = None) -> None:
    settings = get_settings()
    r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    queues = list(queue_names or DEFAULT_QUEUES)
    consumer_id = consumer_name or f"{socket.gethostname()}:{os.getpid()}"

    _ensure_groups(r, queues)

    streams: dict[str, str] = {f"jobs:{q}": ">" for q in queues}

    logger.info("worker started: queues=%s consumer=%s", queues, consumer_id)
    while not _should_stop:
        try:
            resp = r.xreadgroup(
                groupname=GROUP,
                consumername=consumer_id,
                streams=streams,
                count=8,
                block=POLL_BLOCK_MS,
            )
        except redis.ConnectionError:
            logger.exception("redis connection error; backing off")
            time.sleep(2)
            continue

        if not resp:
            continue

        for stream, messages in resp:
            for msg_id, fields in messages:
                _process(r, stream, msg_id, fields)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    run()


if __name__ == "__main__":
    main()


__all__ = ["main", "run"]
