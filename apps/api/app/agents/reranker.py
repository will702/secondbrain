"""Reranker: Qwen3-Reranker-0.6B via the local-ai stack (~/ai, port 8080).

Scores query/document pairs AFTER vector search so only the best chunks reach
the LLM. Retrieval stays deterministic: when the reranker is disabled or
unreachable, callers keep their fused ordering (scores of None).
"""

import logging
import threading

import httpx

from app.core.config import get_settings

logger = logging.getLogger("secondbrain.reranker")


def rerank(query: str, texts: list[str]) -> list[float] | None:
    """Return one score per text (same order), or None when unavailable."""
    settings = get_settings()
    if not settings.reranker_enabled or not texts:
        return None
    base = (settings.reranker_base_url or settings.embedding_base_url
            or settings.llm_base_url).rstrip("/")
    try:
        response = httpx.post(
            f"{base}/rerank",
            json={"query": query, "documents": texts},
            timeout=120.0,
        )
        response.raise_for_status()
        results = response.json()["results"]
        scores = [0.0] * len(texts)
        for item in results:
            scores[item["index"]] = float(item["relevance_score"])
        return scores
    except Exception as exc:  # noqa: BLE001 — retrieval must not hard-fail
        logger.warning("reranker unavailable (%s); keeping fused order", exc)
        return None


# --- process-level circuit breaker: one warning per outage window -----------

_unavailable_until: float = 0.0
_lock = threading.Lock()


def rerank_with_breaker(query: str, texts: list[str]) -> list[float] | None:
    """rerank() with a cool-down so a down server is probed at most once/min."""
    global _unavailable_until
    import time

    with _lock:
        if time.monotonic() < _unavailable_until:
            return None
    scores = rerank(query, texts)
    if scores is None:
        with _lock:
            _unavailable_until = time.monotonic() + 60.0
    return scores


def reset_breaker() -> None:
    """Test hook."""
    global _unavailable_until
    with _lock:
        _unavailable_until = 0.0
