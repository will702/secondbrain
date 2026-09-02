import os

import pytest
import sqlalchemy
from sqlalchemy.orm import sessionmaker

# Test database isolation: separate schema on the same local Postgres.
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://secondbrain:secondbrain@localhost:5433/secondbrain_test",
)


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    """Create secondbrain_test and run migrations once per test session."""
    from app.core.db import Base
    import app.models  # noqa: F401

    server_url = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    server_engine = sqlalchemy.create_engine(
        server_url, pool_pre_ping=True, isolation_level="AUTOCOMMIT"
    )
    with server_engine.connect() as conn:
        existing = conn.execute(
            sqlalchemy.text(
                "SELECT 1 FROM pg_database WHERE datname = 'secondbrain_test'"
            )
        ).scalar()
        if not existing:
            conn.execute(sqlalchemy.text("CREATE DATABASE secondbrain_test"))
    server_engine.dispose()

    engine = sqlalchemy.create_engine(TEST_DB_URL, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(_test_database):
    """Function-scoped session with a clean slate: truncate all tables after each test."""
    connection = _test_database.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, expire_on_commit=False)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()
