from fastapi.testclient import TestClient

from app.main import app
from app.models import DbSession, User


def _register(client: TestClient, email="user@test.dev", password="correct-horse-battery"):
    return client.post(
        "/auth/register",
        json={"email": email, "password": password, "display_name": "Test User"},
    )


def test_register_login_logout_flow(db):
    with TestClient(app) as client:
        response = _register(client)
        assert response.status_code == 201
        assert response.json()["email"] == "user@test.dev"
        assert "sb_session" in response.cookies

        # Session cookie grants access.
        assert client.get("/auth/me").status_code == 200

        # Logout revokes the session.
        assert client.post("/auth/logout").status_code == 204
        assert client.get("/auth/me").status_code == 401

        # Re-login with correct password.
        response = client.post(
            "/auth/login", json={"email": "user@test.dev", "password": "correct-horse-battery"}
        )
        assert response.status_code == 200
        assert client.get("/auth/me").status_code == 200


def test_register_duplicate_email_rejected(db):
    with TestClient(app) as client:
        assert _register(client).status_code == 201
        assert _register(client).status_code == 409


def test_login_wrong_password_rejected(db):
    with TestClient(app) as client:
        _register(client)
        response = client.post(
            "/auth/login", json={"email": "user@test.dev", "password": "wrong-password-1"}
        )
        assert response.status_code == 401


def test_passwords_hashed_not_stored(db):
    with TestClient(app) as client:
        _register(client)
    user = db.query(User).filter_by(email="user@test.dev").one()
    assert "correct-horse" not in user.password_hash
    assert user.password_hash.startswith("$argon2")


def test_session_tokens_stored_hashed(db):
    with TestClient(app) as client:
        _register(client)
    sessions = db.query(DbSession).all()
    assert sessions and all(not s.token_hash.startswith("sb") for s in sessions)
    assert all(len(s.token_hash) == 64 for s in sessions)  # sha256 hex


def test_short_password_rejected(db):
    with TestClient(app) as client:
        response = client.post(
            "/auth/register",
            json={"email": "x@test.dev", "password": "short", "display_name": "X"},
        )
        assert response.status_code == 422
