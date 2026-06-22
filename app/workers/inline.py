"""In-process job drainer for demo / single-process deployments.

In production a separate worker process consumes jobs from Redis Streams via
`app.workers.consumer`. For deployments where no worker exists (most notably
the demo, which uses `InMemoryJobQueue`), this module lets the API process
drain its own queue synchronously right after enqueueing — so the
end-to-end flow (upload → extract → classify → draft) completes within a
single HTTP request and the Review Queue immediately shows the draft.

This is **demo-grade**: it runs work on the request thread (slow uploads
get slower) and has no retry semantics beyond what `dispatch_payload`
provides. The real worker is the production answer.
"""
from __future__ import annotations

import logging

from app.workers.jobs import dispatch_payload
from app.workers.queue import InMemoryJobQueue, JobQueue

logger = logging.getLogger(__name__)

# Queue names the dispatcher knows about. Keep in sync with `app.workers.jobs`.
_DRAINABLE_QUEUES = ("extract", "classify")

# Safety bound: each handler can enqueue follow-up work, so we loop until the
# queues are stable. This caps runaway pipelines (shouldn't happen in
# practice — extract enqueues classify, and classify is terminal).
_MAX_ITERATIONS = 10


def drain_in_process(queue: JobQueue) -> int:
    """Drain all known queues by dispatching each payload in-process.

    Returns the number of jobs dispatched. No-op (returns 0) for queues that
    aren't `InMemoryJobQueue` — Redis-backed deployments have a real worker.
    """
    if not isinstance(queue, InMemoryJobQueue):
        return 0

    total = 0
    for _ in range(_MAX_ITERATIONS):
        drained_this_round = 0
        for name in _DRAINABLE_QUEUES:
            items = queue.drain(name)
            for job_id, payload in items:
                try:
                    dispatch_payload(payload)
                except Exception:  # noqa: BLE001 — log + continue
                    logger.exception(
                        "in-process job dispatch failed",
                        extra={"job_id": job_id, "payload_type": payload.get("type")},
                    )
                drained_this_round += 1
        if drained_this_round == 0:
            break
        total += drained_this_round
    return total


__all__ = ["drain_in_process"]
