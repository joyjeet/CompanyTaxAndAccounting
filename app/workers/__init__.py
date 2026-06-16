"""Worker / queue layer.

Stub-only for now. Provides a Redis client and an abstract `JobQueue` so the
domain layer can enqueue work without depending on the concrete backend. No
real jobs are wired up yet.
"""
from app.workers.queue import JobQueue, RedisJobQueue, get_job_queue

__all__ = ["JobQueue", "RedisJobQueue", "get_job_queue"]
