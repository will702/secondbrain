"""Embedding provider: fastembed (local ONNX) with a deterministic fake for tests.

Interface: embed_texts(list[str]) -> list[list[float]] with dim == settings.embedding_dim.
"""

import hashlib
import logging
import threading

from app.core.config import get_settings

logger = logging.getLogger("secondbrain.embeddings")


class EmbeddingProvider:
    name: str = "base"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class FastEmbedProvider(EmbeddingProvider):
    def __init__(self) -> None:
        from fastembed import TextEmbedding

        self.settings = get_settings()
        self._model = TextEmbedding(model_name=self.settings.embedding_model)
        self.name = self.settings.embedding_model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [vec.tolist() for vec in self._model.embed(texts)]


class FakeEmbedProvider(EmbeddingProvider):
    """Deterministic hash-projection vectors — tests only, never production."""

    name = "fake-hash"

    def __init__(self, dim: int | None = None):
        self.dim = dim or get_settings().embedding_dim

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).digest()
            values = []
            for i in range(self.dim):
                byte = digest[i % len(digest)]
                values.append((byte / 255.0) * 2 - 1)
            out.append(values)
        return out


_provider: EmbeddingProvider | None = None
_provider_lock = threading.Lock()


def get_embedder() -> EmbeddingProvider:
    global _provider
    with _provider_lock:
        if _provider is None:
            try:
                _provider = FastEmbedProvider()
                logger.info("embeddings ready", extra={"purpose": "embed"})
            except Exception as exc:
                logger.warning(
                    "fastembed unavailable (%s); using deterministic fake — set EMBEDDING_PROVIDER=fastembed when the model is downloaded",
                    exc,
                )
                _provider = FakeEmbedProvider()
        return _provider


def set_embedder(provider: EmbeddingProvider) -> None:
    """Test hook."""
    global _provider
    with _provider_lock:
        _provider = provider
