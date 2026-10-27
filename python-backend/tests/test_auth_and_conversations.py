from fastapi.testclient import TestClient

from conftest import register


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


def test_chat_does_not_claim_success_when_local_model_is_unavailable(
    client: TestClient, monkeypatch
) -> None:
    register(client, "offline@example.com")
    created = client.post(
        "/api/v1/conversations",
        json={"title": "Local chat"},
        headers={"X-CSRF-Token": client.cookies["louf_csrf"]},
    )

    async def unavailable_models():
        return {
            "connected": False,
            "provider": "Ollama",
            "models": [],
            "message": "Ollama is not reachable.",
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
