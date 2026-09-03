"""Embedding providers.

- LocalAIEmbedProvider: the ~/ai local-ai stack (Qwen3-Embedding-0.6B, 1024-d,
  instruction-aware query embedding) over its OpenAI-style /v1/embeddings API.
- FastEmbedProvider: local ONNX fallback (BAAI/bge-small-en-v1.5, 384-d).
- FakeEmbedProvider: deterministic hash vectors — tests only.

Interface: embed_texts(list[str]) -> list[list[float]] with
dim == settings.embedding_dim; embed_query(str) for retrieval-side embedding
(defaults to embed_texts — only LocalAI uses a different query form).
"""

import hashlib
import logging
import threading

import httpx

from app.core.config import get_settings

logger = logging.getLogger("secondbrain.embeddings")


class EmbeddingProvider:
    name: str = "base"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]


class LocalAIEmbedProvider(EmbeddingProvider):
    """Qwen3-Embedding-0.6B served by the local-ai stack (~/ai, port 8080).

    Documents embed raw; queries use the model's instruction prefix
    (`"query": true`) which measurably improves retrieval-side quality.
    """

    def __init__(self, base_url: str | None = None, timeout: float = 120.0):
        self.settings = get_settings()
        self.base_url = (
            base_url or self.settings.embedding_base_url or self.settings.llm_base_url
        ).rstrip("/")
        self.timeout = timeout
        self.name = "local-ai:Qwen3-Embedding-0.6B"

    def _embed(self, payload: dict) -> list[list[float]]:
        response = httpx.post(f"{self.base_url}/embeddings", json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()["data"]
        vectors = [item["embedding"] for item in sorted(data, key=lambda d: d["index"])]
        expected = self.settings.embedding_dim
        for vector in vectors:
            if len(vector) != expected:
                raise RuntimeError(
                    f"local-ai returned {len(vector)}-d vectors but the schema is "
                    f"{expected}-d — check EMBEDDING_DIM vs config/config.yaml"
                )
        return vectors

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self._embed({"input": texts})

    def embed_query(self, text: str) -> list[float]:
        return self._embed({"input": text, "query": True})[0]


class FastEmbedProvider(EmbeddingProvider):
    def __init__(self) -> None:
        from fastembed import TextEmbedding

        self.settings = get_settings()
        self._model = TextEmbedding(model_name=self.settings.embedding_model)
        self.name = self.settings.embedding_model


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


def _build_provider() -> EmbeddingProvider:
    settings = get_settings()
    choice = settings.embedding_provider
    if choice == "fake":
        return FakeEmbedProvider()
    if choice == "fastembed":
        return FastEmbedProvider()
    if choice == "localai":
        return LocalAIEmbedProvider()
    raise ValueError(f"unknown EMBEDDING_PROVIDER {choice!r} (localai | fastembed | fake)")


def get_embedder() -> EmbeddingProvider:
    global _provider
    with _provider_lock:
        if _provider is None:
            _provider = _build_provider()
            logger.info(
                "embeddings ready via %s (%d-d)", _provider.name, get_settings().embedding_dim
            )
        return _provider


def set_embedder(provider: EmbeddingProvider) -> None:
    """Test hook."""
    global _provider
    with _provider_lock:
        _provider = provider
