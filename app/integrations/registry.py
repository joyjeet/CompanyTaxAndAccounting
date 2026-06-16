"""Process-wide registry of pluggable integrations.

The application defaults to deterministic mock implementations so tests never
need network or Azure resources. Production wires real Azure services in via
`bootstrap.bootstrap_from_settings()` (or similar) at startup.

Tests inject mocks with the `set_*()` helpers from a fixture and reset them
in teardown.
"""
from __future__ import annotations

from threading import Lock

from app.integrations.llm import LLMClassifier, MockLLMClassifier
from app.integrations.ocr import DocumentExtractor, MockDocumentExtractor
from app.integrations.storage import LocalFilesystemStorage, StorageService
from app.workers.queue import JobQueue, get_job_queue

_lock = Lock()

_storage: StorageService | None = None
_extractor: DocumentExtractor | None = None
_classifier: LLMClassifier | None = None
_queue: JobQueue | None = None


def _default_storage() -> StorageService:
    return LocalFilesystemStorage()


def _default_extractor() -> DocumentExtractor:
    return MockDocumentExtractor()


def _default_classifier() -> LLMClassifier:
    return MockLLMClassifier()


# --------------------------------------------------------------------------- #
# Getters
# --------------------------------------------------------------------------- #
def get_storage() -> StorageService:
    global _storage
    with _lock:
        if _storage is None:
            _storage = _default_storage()
        return _storage


def get_extractor() -> DocumentExtractor:
    global _extractor
    with _lock:
        if _extractor is None:
            _extractor = _default_extractor()
        return _extractor


def get_classifier() -> LLMClassifier:
    global _classifier
    with _lock:
        if _classifier is None:
            _classifier = _default_classifier()
        return _classifier


def get_queue() -> JobQueue:
    global _queue
    with _lock:
        if _queue is None:
            _queue = get_job_queue()
        return _queue


# --------------------------------------------------------------------------- #
# Setters (test-only)
# --------------------------------------------------------------------------- #
def set_storage(svc: StorageService | None) -> None:
    global _storage
    with _lock:
        _storage = svc


def set_extractor(svc: DocumentExtractor | None) -> None:
    global _extractor
    with _lock:
        _extractor = svc


def set_classifier(svc: LLMClassifier | None) -> None:
    global _classifier
    with _lock:
        _classifier = svc


def set_queue(svc: JobQueue | None) -> None:
    global _queue
    with _lock:
        _queue = svc


def reset() -> None:
    """Reset all integrations to their defaults. Call from test teardown."""
    set_storage(None)
    set_extractor(None)
    set_classifier(None)
    set_queue(None)


__all__ = [
    "get_classifier",
    "get_extractor",
    "get_queue",
    "get_storage",
    "reset",
    "set_classifier",
    "set_extractor",
    "set_queue",
    "set_storage",
]
