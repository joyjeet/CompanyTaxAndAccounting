"""External integration interfaces.

The dev/test defaults use mock or local-filesystem implementations; Azure
implementations exist behind the same ABCs and lazy-import their SDKs so
they're optional at install time.
"""
from app.integrations.keys import AzureKeyVaultKeyProvider, KeyProvider, StubKeyProvider
from app.integrations.llm import (
    AzureOpenAIClassifier,
    Classification,
    LLMClassifier,
    MockLLMClassifier,
)
from app.integrations.ocr import (
    AzureDocumentIntelligenceExtractor,
    DocumentExtractor,
    ExtractionResult,
    MockDocumentExtractor,
)
from app.integrations.storage import (
    AzureBlobStorage,
    LocalFilesystemStorage,
    StorageService,
    StoredObject,
)

__all__ = [
    "AzureBlobStorage",
    "AzureDocumentIntelligenceExtractor",
    "AzureKeyVaultKeyProvider",
    "AzureOpenAIClassifier",
    "Classification",
    "DocumentExtractor",
    "ExtractionResult",
    "KeyProvider",
    "LLMClassifier",
    "LocalFilesystemStorage",
    "MockDocumentExtractor",
    "MockLLMClassifier",
    "StorageService",
    "StoredObject",
    "StubKeyProvider",
]
