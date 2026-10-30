from fastapi.testclient import TestClient

from conftest import register
from app.core.config import settings
from app.models.entities import User
from conftest import TestingSession


def test_registration_creates_secure_authenticated_session(client: TestClient) -> None:
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "Person@Example.com", "password": "a-strong-test-password"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 201
    assert response.json()["email"] == "person@example.com"
    assert "password_hash" not in response.json()
    assert client.cookies.get("louf_session")
    assert client.cookies.get("louf_csrf")
    assert "httponly" in response.headers["set-cookie"].lower()
    assert client.get("/api/v1/users/me").json()["email"] == "person@example.com"


def test_registration_rejects_weak_password(client: TestClient) -> None:
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "weak@example.com", "password": "short"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 422


def test_whitespace_only_titles_are_rejected(client: TestClient) -> None:
    register(client, "titles@example.com")
    response = client.post(
        "/api/v1/conversations",
        json={"title": "   "},
        headers={"X-CSRF-Token": client.cookies["louf_csrf"]},
    )
    assert response.status_code == 422


def test_guest_session_is_isolated_and_deleted_on_logout(client: TestClient) -> None:
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    response = client.post("/api/v1/auth/guest", headers={"X-CSRF-Token": csrf})

    assert response.status_code == 201
    guest = response.json()
    assert guest["is_guest"] is True
    assert guest["role"] == "guest"
    created = client.post(
        "/api/v1/conversations",
        json={"title": "Temporary conversation"},
        headers={"X-CSRF-Token": client.cookies["louf_csrf"]},
    )
    assert created.status_code == 201

    client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": client.cookies["louf_csrf"]},
    )
    assert client.get("/api/v1/users/me").status_code == 401
    with TestingSession() as db:
        assert db.get(User, guest["id"]) is None


def test_conversation_rename_is_validated_and_user_scoped(client: TestClient) -> None:
    register(client, "rename@example.com")
    created = client.post(
        "/api/v1/conversations",
        json={"title": "Old title"},
        headers={"X-CSRF-Token": client.cookies["louf_csrf"]},
    )
    conversation_id = created.json()["id"]
    renamed = client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"title": "  A better title  "},
        headers={"X-CSRF-Token": client.cookies["louf_csrf"]},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "A better title"

    client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": client.cookies["louf_csrf"]},
    )
    register(client, "rename-other@example.com")
    denied = client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"title": "Not mine"},
        headers={"X-CSRF-Token": client.cookies["louf_csrf"]},
    )
    assert denied.status_code == 404


def test_password_reset_expires_consumes_token_and_revokes_sessions(
    client: TestClient, monkeypatch
) -> None:
    register(client, "reset@example.com")
    monkeypatch.setattr(settings, "smtp_host", "mail.example.test")
    monkeypatch.setattr(settings, "smtp_from_email", "louf@example.test")
    delivered: list[str] = []
    monkeypatch.setattr(
        "app.api.routes.send_password_reset_email",
        lambda email, token: delivered.append(token),
    )
    csrf = client.cookies["louf_csrf"]
    requested = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset@example.com"},
        headers={"X-CSRF-Token": csrf},
    )
    assert requested.status_code == 200
    assert "token" not in requested.json()
    assert len(delivered) == 1

    reset = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": delivered[0], "password": "a-new-strong-password"},
        headers={"X-CSRF-Token": csrf},
    )
    assert reset.status_code == 200
    assert client.get("/api/v1/users/me").status_code == 401
    reused = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": delivered[0], "password": "another-strong-password"},
        headers={"X-CSRF-Token": csrf},
    )
    assert reused.status_code == 400

    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "reset@example.com", "password": "a-new-strong-password"},
        headers={"X-CSRF-Token": csrf},
    )
    assert login.status_code == 200


def test_password_recovery_reports_missing_smtp_configuration(client: TestClient) -> None:
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "unknown@example.com"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 503


def test_local_frontend_origins_can_register(client: TestClient) -> None:
    for index, origin in enumerate(("http://localhost:5173", "http://127.0.0.1:5173")):
        csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": f"local{index}@example.com",
                "password": "a-strong-test-password",
            },
            headers={"X-CSRF-Token": csrf, "Origin": origin},
        )
        assert response.status_code == 201
        client.post(
            "/api/v1/auth/logout",
            headers={"X-CSRF-Token": client.cookies["louf_csrf"], "Origin": origin},
        )


def test_untrusted_origin_cannot_register(client: TestClient) -> None:
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "origin-denied@example.com", "password": "a-strong-test-password"},
        headers={"X-CSRF-Token": csrf, "Origin": "https://attacker.example"},
    )
    assert response.status_code == 403


def test_login_logout_and_conversation_ownership(client: TestClient) -> None:
    register(client, "one@example.com")
    created = client.post(
        "/api/v1/conversations",
        json={"title": "Private chat"},
        headers={"X-CSRF-Token": client.cookies["louf_csrf"]},
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": client.cookies["louf_csrf"]},
    )
    assert client.get("/api/v1/users/me").status_code == 401

    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    logged_in = client.post(
        "/api/v1/auth/login",
        json={"email": "one@example.com", "password": "a-strong-test-password"},
        headers={"X-CSRF-Token": csrf},
    )
    assert logged_in.status_code == 200
    assert client.get("/api/v1/conversations").json()[0]["id"] == conversation_id

    client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": client.cookies["louf_csrf"]},
    )
    register(client, "two@example.com")
    missing = client.get(f"/api/v1/conversations/{conversation_id}/messages")
    assert missing.status_code == 404


def test_unsafe_requests_require_csrf(client: TestClient) -> None:
    register(client, "csrf@example.com")
    response = client.post("/api/v1/conversations", json={"title": "Blocked"})
    assert response.status_code == 403


def test_chat_does_not_claim_success_when_bionic_is_unavailable(
    client: TestClient, monkeypatch
) -> None:
    register(client, "offline@example.com")
    created = client.post(
        "/api/v1/conversations",
        json={"title": "Bionic chat"},
        headers={"X-CSRF-Token": client.cookies["louf_csrf"]},
    )

    async def unavailable_models():
        return {
            "connected": False,
            "provider": "Bionic",
            "models": [],
            "message": "Bionic is not reachable.",
        }

    monkeypatch.setattr("app.api.routes.list_models", unavailable_models)
    response = client.post(
        f"/api/v1/conversations/{created.json()['id']}/messages",
        json={"prompt": "Hello", "model": "missing"},
        headers={"X-CSRF-Token": client.cookies["louf_csrf"]},
    )

    assert response.status_code == 503
    messages = client.get(
        f"/api/v1/conversations/{created.json()['id']}/messages"
    ).json()
    assert messages == []
