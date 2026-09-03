import os

# Hermetic tests: point the LLM at an unroutable port unless a test explicitly
# overrides it. Without this, a locally running MLX/Ollama server would make
# unit tests do real (slow) model calls.
os.environ.setdefault("LLM_BASE_URL", "http://127.0.0.1:9/v1")

import pytest
import sqlalchemy
from sqlalchemy.orm import sessionmaker

from app.core.db import Base, get_db
from app.main import app

# Tests run against a dedicated database on the same local Postgres.
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://secondbrain:secondbrain@localhost:5433/secondbrain_test",
)

_engine: sqlalchemy.Engine | None = None
_TestSessionLocal: sessionmaker | None = None


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    """Create secondbrain_test and all tables once per test session."""
    global _engine, _TestSessionLocal
    import app.models  # noqa: F401 — register mappers

    server_engine = sqlalchemy.create_engine(
        TEST_DB_URL.rsplit("/", 1)[0] + "/postgres", pool_pre_ping=True,
        isolation_level="AUTOCOMMIT",
    )
    with server_engine.connect() as conn:
        exists = conn.execute(
            sqlalchemy.text("SELECT 1 FROM pg_database WHERE datname = 'secondbrain_test'")
        ).scalar()
        if not exists:
            conn.execute(sqlalchemy.text("CREATE DATABASE secondbrain_test"))
    server_engine.dispose()

    _engine = sqlalchemy.create_engine(TEST_DB_URL, pool_pre_ping=True)
    with _engine.begin() as conn:
        conn.execute(sqlalchemy.text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(_engine)
    _TestSessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    yield _engine
    _engine.dispose()
    _engine = None


def _truncate_all() -> None:
    tables = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
    with _engine.begin() as conn:
        conn.execute(sqlalchemy.text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def _clean_db(_test_database):
    """Clean slate per test + route the app's get_db at the test database."""
    _truncate_all()

    def override():
        session = _TestSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def db(_test_database):
    session = _TestSessionLocal()
    yield session
    session.close()


@pytest.fixture
def fake_embeddings():
    """Deterministic hash embeddings — no model download in tests."""
    from app.agents.embeddings import FakeEmbedProvider, set_embedder

    set_embedder(FakeEmbedProvider())
    yield
    set_embedder(FakeEmbedProvider())
