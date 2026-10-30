import json

import httpx
from fastapi.testclient import TestClient

from app.api import routes
from app.core.config import settings
from conftest import register


def install_provider_mock(monkeypatch, handler) -> None:
    async_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        routes.httpx,
        "AsyncClient",
        lambda *args, **kwargs: async_client(*args, transport=transport, **kwargs),
    )


def test_model_discovery_uses_configured_bionic_endpoint(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "bionic_api_base_url", "https://bionic.example/v1")
    monkeypatch.setattr(settings, "bionic_api_key", "test-token")

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://bionic.example/v1/models"
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(200, json={"data": [{"id": "chat-model"}]})

    install_provider_mock(monkeypatch, handle)
    response = client.get("/api/v1/models")

    assert response.status_code == 200
    assert response.json() == {
        "connected": True,
        "provider": "Bionic",
        "models": [{"name": "chat-model", "size": None}],
        "message": None,
    }


def test_bionic_stream_is_saved_and_credentials_stay_server_side(
    client: TestClient, monkeypatch
) -> None:
    register(client, "bionic@example.com")
    created = client.post(
        "/api/v1/conversations",
        json={"title": "New conversation"},
        headers={"X-CSRF-Token": client.cookies["louf_csrf"]},
    )
    monkeypatch.setattr(settings, "bionic_api_base_url", "https://bionic.example/v1")
    monkeypatch.setattr(settings, "bionic_api_key", "test-token")

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "chat-model"}]})
        assert request.url.path.endswith("/chat/completions")
        payload = json.loads(request.content)
        assert payload["model"] == "chat-model"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
                b'data: {"choices":[{"delta":{"content":" there."}}]}\n\n'
                b"data: [DONE]\n\n"
            ),
        )

    install_provider_mock(monkeypatch, handle)
    response = client.post(
        f"/api/v1/conversations/{created.json()['id']}/messages",
        json={"prompt": "Hello", "model": "chat-model"},
        headers={"X-CSRF-Token": client.cookies["louf_csrf"]},
    )

    assert response.status_code == 200
    assert '"delta": "Hello"' in response.text
    assert '"delta": " there."' in response.text
    assert '"done": true' in response.text
    saved = client.get(
        f"/api/v1/conversations/{created.json()['id']}/messages"
    ).json()
    assert [message["content"] for message in saved] == ["Hello", "Hello there."]
    assert "test-token" not in response.text


def test_unconfigured_bionic_is_reported_without_claiming_connection(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "bionic_api_base_url", "")

    response = client.get("/api/v1/models")

    assert response.status_code == 200
    assert response.json()["connected"] is False
    assert response.json()["provider"] == "Bionic"
    assert "BIONIC_API_BASE_URL" in response.json()["message"]
