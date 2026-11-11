import json
from itertools import count

import httpx
import pytest
from conftest import register
from fastapi.testclient import TestClient

from app.core.config import settings
from app.models.entities import MediaJob
from app.services import media_generation


def test_comfyui_submission_uses_configured_workflow_and_prompt(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow_path = tmp_path / "image-api.json"
    workflow_path.write_text(
        json.dumps({"6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old prompt"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "comfyui_api_base_url", "http://comfyui.test")
    monkeypatch.setattr(settings, "comfyui_image_workflow_path", str(workflow_path))
    monkeypatch.setattr(settings, "comfyui_image_prompt_node_id", "6")
    monkeypatch.setattr(settings, "comfyui_image_prompt_input", "text")

    original_client = httpx.Client
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/prompt"
        payload = json.loads(request.content)
        assert payload["prompt"]["6"]["inputs"]["text"] == "a red fox"
        return httpx.Response(200, json={"prompt_id": "job-123"})

    monkeypatch.setattr(
        media_generation.httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs),
    )

    assert media_generation.submit_generation("image", "a red fox") == "job-123"
    assert len(requests) == 1


def test_video_workflow_prefers_video_outputs() -> None:
    output = media_generation._find_output(
        {
            "outputs": {
                "7": {
                    "images": [{"filename": "preview.png"}],
                    "gifs": [{"filename": "clip.mp4", "type": "output"}],
                }
            }
        },
        "video",
    )
    assert output == {"filename": "clip.mp4", "subfolder": "", "type": "output"}


def test_refresh_generation_tracks_comfyui_queue_state(monkeypatch: pytest.MonkeyPatch) -> None:
    job = MediaJob(
        user_id="user-id",
        media_type="image",
        prompt="A cabin",
        provider_prompt_id="provider-id",
    )
    responses: dict[str, object] = {
        "/history/provider-id": {},
        "/queue": {
            "queue_running": [],
            "queue_pending": [[1, "provider-id", {}, {}, []]],
        },
    }
    monkeypatch.setattr(media_generation, "_get_provider_json", lambda path: responses[path])

    media_generation.refresh_generation(job)
    assert job.status == "queued"

    responses["/queue"] = {"queue_running": [[1, "provider-id", {}, {}, []]], "queue_pending": []}
    media_generation.refresh_generation(job)
    assert job.status == "processing"

    responses["/queue"] = {"queue_running": [], "queue_pending": []}
    media_generation.refresh_generation(job)
    assert job.status == "failed"
    assert job.error


def test_stored_media_paths_cannot_escape_storage_directory(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    with pytest.raises(media_generation.MediaProviderError):
        media_generation.resolve_stored_media("../outside.png")


def test_media_jobs_are_private_persisted_and_deletable(
    client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(client, "media-owner@example.com")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    provider_job_ids = count()
    monkeypatch.setattr(
        "app.api.routes.submit_generation",
        lambda media_type, prompt: f"provider-job-{next(provider_job_ids)}",
    )

    created = client.post(
        "/api/v1/media/jobs",
        json={"media_type": "image", "prompt": "A cabin at sunrise"},
        headers={"X-CSRF-Token": client.cookies["louf_csrf"]},
    )
    assert created.status_code == 202, created.text
    job = created.json()
    assert job["status"] == "queued"
    assert job["file_url"] is None

    def complete(job: MediaJob) -> None:
        path = tmp_path / "storage" / "media" / job.user_id / f"{job.id}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"generated-image")
        job.status = "completed"
        job.file_path = f"media/{job.user_id}/{job.id}.png"

    monkeypatch.setattr("app.api.routes.refresh_generation", complete)
    refreshed = client.get(f"/api/v1/media/jobs/{job['id']}")
    assert refreshed.status_code == 200
    assert refreshed.json()["status"] == "completed"
    assert client.get(refreshed.json()["file_url"]).content == b"generated-image"
    assert len(client.get("/api/v1/media/jobs").json()) == 1

    csrf = client.cookies["louf_csrf"]
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    register(client, "media-other@example.com")
    assert client.get(f"/api/v1/media/jobs/{job['id']}").status_code == 404
    assert client.get(f"/api/v1/media/jobs/{job['id']}/file").status_code == 404

    owned = client.post(
        "/api/v1/media/jobs",
        json={"media_type": "image", "prompt": "An ocean"},
        headers={"X-CSRF-Token": client.cookies["louf_csrf"]},
    )
    assert owned.status_code == 202
    deleted = client.delete(
        f"/api/v1/media/jobs/{owned.json()['id']}",
        headers={"X-CSRF-Token": client.cookies["louf_csrf"]},
    )
    assert deleted.status_code == 204
