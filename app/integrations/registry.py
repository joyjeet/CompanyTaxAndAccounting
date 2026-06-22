"""Process-wide registry of pluggable integrations.

The application defaults to deterministic mock implementations so tests never
need network or Azure resources. Production wires real Azure services in via
`bootstrap.bootstrap_from_settings()` (or similar) at startup.

Tests inject mocks with the `set_*()` helpers from a fixture and reset them
in teardown.
"""
from __future__ import annotations

from threading import Lock

from app.integrations.account_categorizer import (
    AccountCategorizer,
    DictionaryCategorizer,
)
from app.integrations.llm import LLMClassifier, MockLLMClassifier
from app.integrations.ocr import DocumentExtractor, MockDocumentExtractor
from app.integrations.storage import LocalFilesystemStorage, StorageService
from app.workers.queue import JobQueue, get_job_queue

_lock = Lock()

_storage: StorageService | None = None
_extractor: DocumentExtractor | None = None
_classifier: LLMClassifier | None = None
_queue: JobQueue | None = None
_categorizer: AccountCategorizer | None = None


def _default_storage() -> StorageService:
    return LocalFilesystemStorage()


def _default_extractor() -> DocumentExtractor:
    return MockDocumentExtractor()


def _default_categorizer() -> AccountCategorizer:
    return DictionaryCategorizer()


def _default_classifier() -> LLMClassifier:
    return MockLLMClassifier(categorizer=get_categorizer())


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


def get_categorizer() -> AccountCategorizer:
    global _categorizer
    with _lock:
        if _categorizer is None:
            _categorizer = DictionaryCategorizer()
        return _categorizer


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


def set_categorizer(svc: AccountCategorizer | None) -> None:
    global _categorizer
    with _lock:
        _categorizer = svc


def reset() -> None:
    """Reset all integrations to their defaults. Call from test teardown."""
    set_storage(None)
    set_extractor(None)
    set_classifier(None)
    set_queue(None)
    set_categorizer(None)


# --------------------------------------------------------------------------- #
# Production wiring — call once from app startup
# --------------------------------------------------------------------------- #
def bootstrap_from_settings() -> None:
    """Wire integrations from environment settings.

    Idempotent: subsequent calls are no-ops once a backend is installed. Tests
    override via `set_*()` and `reset()` and never call this.

    Today this only wires `storage`. Extractor / classifier / queue stay on
    their mock defaults; production wiring for those will land alongside the
    Azure Document Intelligence + Azure OpenAI integrations.
    """
    from app.core.config import get_settings

    settings = get_settings()

    # ----- storage ----------------------------------------------------- #
    if _storage is None and settings.app_storage_backend == "azure_blob":
        if not settings.azure_storage_account_url:
            raise RuntimeError(
                "app_storage_backend=azure_blob requires azure_storage_account_url"
            )
        # Lazy imports — only pulled in when actually using Azure Blob.
        from azure.identity import DefaultAzureCredential  # type: ignore[import-not-found]

        from app.integrations.storage import AzureBlobStorage

        set_storage(
            AzureBlobStorage(
                account_url=settings.azure_storage_account_url,
                container=settings.azure_storage_container,
                # DefaultAzureCredential picks up:
                #   - Managed Identity in Azure (preferred)
                #   - az CLI login locally
                #   - service principal env vars
                # No connection strings or SAS keys are ever required.
                credential=DefaultAzureCredential(),
            )
        )

    # ----- queue ------------------------------------------------------- #
    if _queue is None and settings.app_queue_backend == "memory":
        from app.workers.queue import InMemoryJobQueue

        set_queue(InMemoryJobQueue())

    # ----- extractor --------------------------------------------------- #
    if (
        _extractor is None
        and settings.app_extractor_backend == "azure_document_intelligence"
    ):
        if not settings.azure_document_intelligence_endpoint:
            raise RuntimeError(
                "app_extractor_backend=azure_document_intelligence requires "
                "azure_document_intelligence_endpoint"
            )
        from app.integrations.ocr import AzureDocumentIntelligenceExtractor

        if settings.azure_document_intelligence_api_key:
            # Key-based auth — useful for early demos and CI; production
            # should switch to Managed Identity by leaving the API key
            # unset.
            from azure.core.credentials import (
                AzureKeyCredential,  # type: ignore[import-not-found]
            )

            credential: object = AzureKeyCredential(
                settings.azure_document_intelligence_api_key
            )
        else:
            from azure.identity import (
                DefaultAzureCredential,  # type: ignore[import-not-found]
            )

            credential = DefaultAzureCredential()

        set_extractor(
            AzureDocumentIntelligenceExtractor(
                endpoint=settings.azure_document_intelligence_endpoint,
                credential=credential,
            )
        )

    # ----- categorizer ------------------------------------------------- #
    # The categorizer must be installed BEFORE the classifier so the
    # MockLLMClassifier picks it up via `_default_classifier`.
    if _categorizer is None and settings.app_categorizer_backend == "azure_openai":
        if not settings.azure_openai_endpoint:
            raise RuntimeError(
                "app_categorizer_backend=azure_openai requires azure_openai_endpoint"
            )
        from app.integrations.account_categorizer import AzureOpenAICategorizer

        set_categorizer(
            AzureOpenAICategorizer(
                endpoint=settings.azure_openai_endpoint,
                api_key=settings.azure_openai_api_key,
                api_version=settings.azure_openai_api_version,
                deployment=settings.azure_openai_deployment,
            )
        )

    # ----- classifier -------------------------------------------------- #
    # Force the default classifier to re-resolve so it picks up whatever
    # categorizer we just installed. Production classifier backends (full
    # Azure OpenAI classify path) can override here in a later phase.
    if _classifier is None:
        set_classifier(MockLLMClassifier(categorizer=get_categorizer()))


__all__ = [
    "bootstrap_from_settings",
    "get_categorizer",
    "get_classifier",
    "get_extractor",
    "get_queue",
    "get_storage",
    "reset",
    "set_categorizer",
    "set_classifier",
    "set_extractor",
    "set_queue",
    "set_storage",
]
