"""Model routing: purpose → model (AI_SYSTEM.md §2). One place to upgrade
quality selectively (extraction vs reasoning vs cheap classification)."""

from app.agents.llm_client import LLMClient
from app.core.config import get_settings


class ModelRouter:
    def __init__(self, client: LLMClient | None = None):
        self.client = client or LLMClient()
        self._settings = get_settings()

    def model_for(self, purpose: str) -> str:
        return {
            "extraction": self._settings.llm_extraction_model,
            "reasoning": self._settings.llm_reasoning_model,
            "classify": self._settings.llm_classify_model,
            "summarize": self._settings.llm_summarize_model,
        }.get(purpose, self._settings.llm_reasoning_model)


_default_router: ModelRouter | None = None


def get_router(client: LLMClient | None = None) -> ModelRouter:
    global _default_router
    if client is not None:
        return ModelRouter(client)
    if _default_router is None:
        _default_router = ModelRouter()
    return _default_router


def set_router(router: ModelRouter) -> None:
    """Test hook."""
    global _default_router
    _default_router = router
