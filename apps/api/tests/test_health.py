from fastapi.testclient import TestClient

from app.main import app


def test_healthz():
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_readyz_reports_components():
    with TestClient(app) as client:
        response = client.get("/readyz")
        body = response.json()
        assert response.status_code in (200, 503)
        assert "database" in body["components"]
        assert "llm" in body["components"]
        # LLM is optional: a missing local model must not kill readiness.
        if not body["components"]["llm"]["ok"]:
            assert body["components"]["llm"]["detail"].startswith("unreachable")


def test_config_loads_defaults():
    from app.core.config import Settings

    settings = Settings()
    assert settings.database_url
    assert settings.embedding_dim == 1024  # local-ai Qwen3-Embedding
