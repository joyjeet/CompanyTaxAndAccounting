"""Job queue abstraction. Real worker process arrives in a later phase."""
from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from functools import lru_cache
from typing import Any

import redis

from app.core.config import get_settings


class JobQueue(ABC):
    @abstractmethod
    def enqueue(self, queue_name: str, payload: dict[str, Any]) -> str:
        """Push a job onto the named queue. Returns the job id (or stream id)."""


class RedisJobQueue(JobQueue):
    def __init__(self, url: str) -> None:
        self._client = redis.Redis.from_url(url, decode_responses=True)

    def enqueue(self, queue_name: str, payload: dict[str, Any]) -> str:
        # Streams give durable, fan-in-friendly semantics.
        return str(
            self._client.xadd(
                f"jobs:{queue_name}",
                {"payload": json.dumps(payload, default=str)},
            )
        )


class InMemoryJobQueue(JobQueue):
    """Test/dev queue. Records enqueued payloads in a dict per queue name and
    exposes a simple `drain()` helper. Not concurrent-safe."""

    def __init__(self) -> None:
        self.queues: dict[str, deque[tuple[str, dict[str, Any]]]] = defaultdict(deque)

    def enqueue(self, queue_name: str, payload: dict[str, Any]) -> str:
        job_id = uuid.uuid4().hex
        # JSON-roundtrip so payload values are stable (Decimals/UUIDs -> strings),
        # mirroring what Redis would do.
        normalised = json.loads(json.dumps(payload, default=str))
        self.queues[queue_name].append((job_id, normalised))
        return job_id

    def drain(self, queue_name: str) -> list[tuple[str, dict[str, Any]]]:
        items = list(self.queues[queue_name])
        self.queues[queue_name].clear()
        return items


@lru_cache(maxsize=1)
def get_job_queue() -> JobQueue:
    """Pick a queue backend based on settings.

    ``app_queue_backend=memory`` returns an InMemoryJobQueue — appropriate
    for demo deployments that drain jobs inline inside the upload request
    (see ``app/api/routes/documents.py``::upload_document). ``redis`` is
    the production default and requires a reachable Redis at ``redis_url``.
    """
    settings = get_settings()
    if settings.app_queue_backend == "memory":
        return InMemoryJobQueue()
    return RedisJobQueue(settings.redis_url)


__all__ = [
    "InMemoryJobQueue",
    "JobQueue",
    "RedisJobQueue",
    "get_job_queue",
]

