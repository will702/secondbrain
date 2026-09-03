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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env").resolve(), env_file_encoding="utf-8", extra="ignore"
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

    # --- LLM (OpenAI-compatible; default: local MLX server) ---
    llm_base_url: str = "http://localhost:8080/v1"
    llm_api_key: str | None = None
    llm_extraction_model: str = "keXjos/Qwen3.8-9B-mlx-4Bit"
    llm_reasoning_model: str = "keXjos/Qwen3.8-9B-mlx-4Bit"
    llm_classify_model: str = "keXjos/Qwen3.8-9B-mlx-4Bit"
    llm_summarize_model: str = "keXjos/Qwen3.8-9B-mlx-4Bit"
    llm_timeout_seconds: float = 300.0
    llm_max_retries: int = 2

    # --- Embeddings (fastembed, local) ---
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

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
