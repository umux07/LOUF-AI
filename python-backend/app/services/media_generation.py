import json
import logging
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx

from app.core.config import settings
from app.models.entities import MediaJob

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".gif"}


class MediaProviderError(Exception):
    pass


def _workflow_settings(media_type: str) -> tuple[str, str, str]:
    if media_type == "image":
        return (
            settings.comfyui_image_workflow_path,
            settings.comfyui_image_prompt_node_id,
            settings.comfyui_image_prompt_input,
        )
    return (
        settings.comfyui_video_workflow_path,
        settings.comfyui_video_prompt_node_id,
        settings.comfyui_video_prompt_input,
    )


def media_provider_configured(media_type: str) -> bool:
    base = urlsplit(settings.comfyui_api_base_url.strip())
    workflow_path, node_id, input_name = _workflow_settings(media_type)
    if base.scheme not in {"http", "https"} or not base.netloc or not node_id or not input_name:
        return False
    return bool(workflow_path and Path(workflow_path).expanduser().is_file())


def _load_workflow(media_type: str, prompt: str) -> dict[str, object]:
    if not media_provider_configured(media_type):
        raise MediaProviderError(
            f"ComfyUI is not configured for {media_type} generation. "
            "Set the ComfyUI API URL, workflow path, prompt node ID, and prompt input name."
        )

    workflow_path, node_id, input_name = _workflow_settings(media_type)
    try:
        workflow = json.loads(Path(workflow_path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        logger.exception("Could not load the configured ComfyUI %s workflow.", media_type)
        raise MediaProviderError("The configured ComfyUI workflow could not be read.") from error

    if not isinstance(workflow, dict):
        raise MediaProviderError("The ComfyUI workflow must be an API-format JSON object.")
    prompt_node = workflow.get(node_id)
    if not isinstance(prompt_node, dict) or not isinstance(prompt_node.get("inputs"), dict):
        raise MediaProviderError("The configured prompt node is not present in the workflow.")
    prompt_node["inputs"][input_name] = prompt
    return workflow


def submit_generation(media_type: str, prompt: str) -> str:
    workflow = _load_workflow(media_type, prompt)
    base_url = settings.comfyui_api_base_url.strip().rstrip("/")
    try:
        with httpx.Client(timeout=min(settings.comfyui_timeout_seconds, 30)) as client:
            response = client.post(
                f"{base_url}/prompt",
                json={"prompt": workflow},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        logger.exception("ComfyUI rejected or failed to accept a %s generation job.", media_type)
        raise MediaProviderError("ComfyUI could not accept the generation request.") from error

    prompt_id = payload.get("prompt_id") if isinstance(payload, dict) else None
    node_errors = payload.get("node_errors") if isinstance(payload, dict) else None
    if node_errors:
        logger.error("ComfyUI reported validation errors for a generation workflow.")
        raise MediaProviderError("ComfyUI could not validate the configured workflow.")
    if not isinstance(prompt_id, str) or not prompt_id.strip():
        logger.error("ComfyUI returned a response without a prompt ID.")
        raise MediaProviderError("ComfyUI returned an invalid generation response.")
    return prompt_id


def _get_provider_json(path: str) -> object:
    base_url = settings.comfyui_api_base_url.strip().rstrip("/")
    try:
        with httpx.Client(timeout=min(settings.comfyui_timeout_seconds, 30)) as client:
            response = client.get(f"{base_url}{path}")
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as error:
        logger.exception("Could not retrieve ComfyUI generation status.")
        raise MediaProviderError("Could not check the generation status with ComfyUI.") from error


def _find_output(record: dict[str, object], media_type: str) -> dict[str, str] | None:
    outputs = record.get("outputs")
    if not isinstance(outputs, dict):
        return None

    preferred_keys = ("videos", "gifs", "images") if media_type == "video" else ("images",)
    for key in preferred_keys:
        for node_output in outputs.values():
            if not isinstance(node_output, dict):
                continue
            files = node_output.get(key)
            if not isinstance(files, list):
                continue
            for item in files:
                if not isinstance(item, dict):
                    continue
                filename = item.get("filename")
                subfolder = item.get("subfolder", "")
                output_type = item.get("type", "output")
                if (
                    isinstance(filename, str)
                    and filename
                    and isinstance(subfolder, str)
                    and isinstance(output_type, str)
                ):
                    return {"filename": filename, "subfolder": subfolder, "type": output_type}
    return None


def _download_output(output: dict[str, str], media_type: str, job: MediaJob) -> str:
    filename = output["filename"]
    extension = Path(filename).suffix.lower()
    allowed_extensions = VIDEO_EXTENSIONS if media_type == "video" else IMAGE_EXTENSIONS
    if extension not in allowed_extensions:
        raise MediaProviderError("ComfyUI produced a file with an unsupported media type.")

    max_bytes = settings.comfyui_max_output_bytes
    if max_bytes <= 0:
        raise MediaProviderError("COMFYUI_MAX_OUTPUT_BYTES must be greater than zero.")

    base_url = settings.comfyui_api_base_url.strip().rstrip("/")
    storage_root = Path(settings.storage_dir).expanduser().resolve()
    relative_path = PurePosixPath("media") / job.user_id / f"{job.id}{extension}"
    destination = storage_root.joinpath(*relative_path.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_name(f"{destination.name}.{uuid4().hex}.tmp")

    try:
        with httpx.Client(timeout=settings.comfyui_timeout_seconds) as client:
            with client.stream(
                "GET",
                f"{base_url}/view",
                params=output,
            ) as response:
                response.raise_for_status()
                content_type = (
                    response.headers.get("content-type", "")
                    .split(";", maxsplit=1)[0]
                    .lower()
                )
                if media_type == "video":
                    allowed_content_type = (
                        content_type.startswith("video/")
                        or content_type == "image/gif"
                        or content_type == "application/octet-stream"
                        or not content_type
                    )
                else:
                    allowed_content_type = (
                        content_type.startswith("image/")
                        or content_type == "application/octet-stream"
                        or not content_type
                    )
                if not allowed_content_type:
                    raise MediaProviderError(
                        "ComfyUI returned a file with an invalid content type."
                    )
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > max_bytes:
                    raise MediaProviderError(
                        "The generated file exceeds the configured size limit."
                    )
                total = 0
                with temporary_path.open("wb") as file:
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise MediaProviderError(
                                "The generated file exceeds the configured size limit."
                            )
                        file.write(chunk)
        temporary_path.replace(destination)
    except (httpx.HTTPError, OSError, ValueError) as error:
        temporary_path.unlink(missing_ok=True)
        logger.exception("Could not store ComfyUI media for job %s.", job.id)
        raise MediaProviderError("ComfyUI could not return the generated file.") from error
    except MediaProviderError:
        temporary_path.unlink(missing_ok=True)
        raise

    return relative_path.as_posix()


def refresh_generation(job: MediaJob) -> None:
    history = _get_provider_json(f"/history/{quote(job.provider_prompt_id, safe='')}")
    if not isinstance(history, dict):
        raise MediaProviderError("ComfyUI returned an invalid generation status.")
    record = history.get(job.provider_prompt_id)
    if not isinstance(record, dict):
        queue = _get_provider_json("/queue")
        running = queue.get("queue_running", []) if isinstance(queue, dict) else []
        pending = queue.get("queue_pending", []) if isinstance(queue, dict) else []
        in_running = any(
            isinstance(item, list)
            and len(item) > 1
            and item[1] == job.provider_prompt_id
            for item in running
        )
        in_pending = any(
            isinstance(item, list)
            and len(item) > 1
            and item[1] == job.provider_prompt_id
            for item in pending
        )
        if in_running:
            job.status = "processing"
        elif in_pending:
            job.status = "queued"
        else:
            job.status = "failed"
            job.error = "ComfyUI no longer has this job in its queue or history."
        return

    status = record.get("status")
    if isinstance(status, dict):
        if status.get("status_str") == "error":
            job.status = "failed"
            job.error = "ComfyUI reported a generation error. Check the ComfyUI server logs."
            return
        if status.get("completed") is not True:
            job.status = "processing"
            return

    output = _find_output(record, job.media_type)
    if not output:
        job.status = "failed"
        job.error = "ComfyUI finished without returning a compatible media file."
        return

    job.file_path = _download_output(output, job.media_type, job)
    job.status = "completed"
    job.error = None


def resolve_stored_media(file_path: str) -> Path:
    root = Path(settings.storage_dir).expanduser().resolve()
    path = (root / file_path).resolve()
    if not path.is_relative_to(root):
        raise MediaProviderError("Stored media path is invalid.")
    return path


def remove_user_media_files(jobs: list[MediaJob]) -> None:
    for job in jobs:
        if job.file_path:
            resolve_stored_media(job.file_path).unlink(missing_ok=True)
