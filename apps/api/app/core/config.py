import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_repo_root() -> Path:
    """Walk up from this file to the directory containing docker-compose.yml
    (the monorepo root — where .env and data/ live)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "docker-compose.yml").exists():
            return parent
    return Path(__file__).resolve().parents[4]


REPO_ROOT = _find_repo_root()

# Frozen/packaged mode can't rely on repo-root discovery — let the launcher
# point us at an explicit env file instead.
ENV_FILE = (
    Path(os.environ["SECONDBRAIN_ENV_FILE"]).resolve()
    if os.environ.get("SECONDBRAIN_ENV_FILE")
    else (REPO_ROOT / ".env").resolve()
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    # --- Core ---
    app_name: str = "Second Brain OS"
    environment: str = "development"
    secret_key: str = "dev-only-secret-key-change-me"
    # Fernet key (base64, 32 bytes) used to encrypt integration tokens at rest.
    secret_encryption_key: str | None = None

    # --- Database ---
    database_url: str = "postgresql+psycopg://secondbrain:secondbrain@localhost:5433/secondbrain"

    # --- Files ---
    data_dir: Path = REPO_ROOT / "data"
    max_upload_mb: int = 50

    # --- Packaged app (standalone runtime) ---
    # Directory of the static web export to serve at "/" (same-origin UI).
    web_dist_dir: Path | None = None

    # --- LLM (OpenAI-compatible; default: local MLX server) ---
    llm_base_url: str = "http://localhost:8080/v1"
    llm_api_key: str | None = None
    # Role aliases resolved server-side by the local-ai stack.
    llm_extraction_model: str = "fast"
    llm_reasoning_model: str = "smart"
    llm_classify_model: str = "fast"
    llm_summarize_model: str = "fast"
    llm_timeout_seconds: float = 300.0
    llm_max_retries: int = 2

    # --- Embeddings (local-ai stack: Qwen3-Embedding-0.6B, 1024-d) ---
    # provider: localai (~/ai stack API) | fastembed (ONNX fallback) | fake (tests)
    embedding_provider: str = "localai"
    # Defaults to the local-ai server co-located with the LLM endpoint.
    embedding_base_url: str | None = None
    embedding_model: str = "Qwen/Qwen3-Embedding-0.6B"
    embedding_dim: int = 1024

    # --- Retrieval reranking (local-ai stack: Qwen3-Reranker-0.6B) ---
    reranker_enabled: bool = True
    reranker_base_url: str | None = None
    rerank_candidates: int = 20

    # --- Sessions / auth ---
    session_ttl_days: int = 30

    # --- Google OAuth (optional; adapter stays dormant without these) ---
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None
    # Exposed on CORS for the web app.
    frontend_origins: list[str] = ["http://localhost:3000"]

    # --- Workers ---
    worker_poll_interval_seconds: float = 1.0
    job_max_attempts: int = 3


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
