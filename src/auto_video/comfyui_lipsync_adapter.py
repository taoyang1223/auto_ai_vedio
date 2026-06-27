from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.request import Request

from .comfyui_wan_adapter import (
    _download_media,
    _load_workflow,
    _multipart_body,
    _queue_prompt,
    _request_json,
    _safe_name,
    _set_input,
    _wait_for_media,
)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ComfyUI lip-sync adapter for auto-video external_command providers")
    parser.add_argument("--base-url")
    parser.add_argument("--base-url-env")
    parser.add_argument("--workflow")
    parser.add_argument("--workflow-env")
    parser.add_argument("--workflow-profile")
    parser.add_argument("--workflow-profile-env")
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--steps", type=int)
    parser.add_argument("--guidance-scale", type=float)
    parser.add_argument("--video-node", default="video")
    parser.add_argument("--video-input", default="video")
    parser.add_argument("--audio-node", default="audio")
    parser.add_argument("--audio-input", default="audio")
    parser.add_argument("--seed-node", default="")
    parser.add_argument("--seed-input", default="seed")
    parser.add_argument("--output-node", default="")
    parser.add_argument("--filename-prefix-input", default="filename_prefix")
    parser.add_argument("--steps-node", action="append", default=[])
    parser.add_argument("--steps-input", default="steps")
    parser.add_argument("--cfg-input", default="cfg")
    parser.add_argument("--upload-endpoint", default="/upload/image")
    parser.add_argument("--video-upload-field", default="image")
    parser.add_argument("--audio-upload-field", default="image")
    parser.add_argument("--upload-type", default="input")
    parser.add_argument("--job", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--output", required=True)
    return parser


def run(args: argparse.Namespace) -> None:
    _apply_workflow_profile(args)
    base_url = _base_url(args).rstrip("/")
    workflow_path = _workflow_path(args)
    payload = json.loads(Path(args.job).read_text(encoding="utf-8"))
    output = Path(args.output)

    video_path = _reference_path(payload, role="source_video", media_type="video")
    audio_path = _reference_path(payload, role="source_audio", media_type="audio")
    if video_path is None:
        raise RuntimeError("lip-sync adapter requires a generated source video reference")
    if audio_path is None:
        raise RuntimeError("lip-sync adapter requires a generated source audio reference")

    uploaded_video = _upload_file(
        base_url,
        args.upload_endpoint,
        video_path,
        field=args.video_upload_field,
        upload_type=args.upload_type,
        timeout=args.timeout,
    )
    uploaded_audio = _upload_file(
        base_url,
        args.upload_endpoint,
        audio_path,
        field=args.audio_upload_field,
        upload_type=args.upload_type,
        timeout=args.timeout,
    )

    workflow = _load_workflow(workflow_path)
    _patch_workflow(
        workflow,
        payload,
        args,
        uploaded_video=_uploaded_name(uploaded_video, video_path),
        uploaded_audio=_uploaded_name(uploaded_audio, audio_path),
    )
    prompt_id = _queue_prompt(base_url, workflow, timeout=args.timeout)
    media = _wait_for_media(base_url, prompt_id, timeout=args.timeout, poll_interval=args.poll_interval)
    body = _download_media(base_url, media, timeout=args.timeout)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(body)
    print(
        json.dumps(
            {
                "prompt_id": prompt_id,
                "media": media,
                "source_video": video_path.as_posix(),
                "source_audio": audio_path.as_posix(),
                "output": output.as_posix(),
            },
            ensure_ascii=False,
        )
    )


def _apply_workflow_profile(args: argparse.Namespace) -> None:
    profile_name = args.workflow_profile
    if not profile_name and args.workflow_profile_env:
        profile_name = os.environ.get(args.workflow_profile_env)
    if not profile_name:
        return
    from .project import load_project
    from .workflow_registry import comfyui_lipsync_adapter_options

    project = load_project(args.project_root)
    for key, value in comfyui_lipsync_adapter_options(project, profile_name).items():
        if key in {"base_url", "base_url_env", "workflow", "workflow_env"} and getattr(args, key, None):
            continue
        setattr(args, key, value)


def _base_url(args: argparse.Namespace) -> str:
    if args.base_url:
        return args.base_url
    if args.base_url_env:
        value = os.environ.get(args.base_url_env)
        if value:
            return value
        raise RuntimeError(f"environment variable {args.base_url_env} is not set")
    raise RuntimeError("ComfyUI base URL is required; pass --base-url or --base-url-env")


def _workflow_path(args: argparse.Namespace) -> Path:
    if args.workflow:
        return Path(args.workflow)
    if args.workflow_env:
        value = os.environ.get(args.workflow_env)
        if value:
            return Path(value)
        raise RuntimeError(f"environment variable {args.workflow_env} is not set")
    raise RuntimeError("ComfyUI workflow path is required; pass --workflow or --workflow-env")


def _reference_path(payload: dict[str, Any], *, role: str, media_type: str) -> Path | None:
    fallback: Path | None = None
    for ref in payload.get("references", []):
        if not isinstance(ref, dict) or not ref.get("exists", False):
            continue
        if ref.get("type") != media_type:
            continue
        absolute_path = ref.get("absolute_path")
        if not absolute_path:
            continue
        path = Path(str(absolute_path))
        if not path.exists():
            continue
        if ref.get("role") == role:
            return path
        fallback = fallback or path
    return fallback


def _upload_file(
    base_url: str,
    endpoint: str,
    path: Path,
    *,
    field: str,
    upload_type: str,
    timeout: float,
) -> dict[str, Any]:
    boundary = f"----auto-video-{uuid.uuid4().hex}"
    endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    body = _multipart_body(
        boundary,
        fields={"type": upload_type, "overwrite": "true"},
        files={field: (path.name, path.read_bytes(), "application/octet-stream")},
    )
    request = Request(
        f"{base_url}{endpoint}",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    return _request_json(request, timeout=timeout)


def _uploaded_name(response: dict[str, Any], source: Path) -> str:
    value = response.get("name") or response.get("filename")
    subfolder = str(response.get("subfolder") or "").strip("/")
    if value:
        name = str(value)
        return f"{subfolder}/{name}" if subfolder else name
    return source.name


def _patch_workflow(
    workflow: dict[str, Any],
    payload: dict[str, Any],
    args: argparse.Namespace,
    *,
    uploaded_video: str,
    uploaded_audio: str,
) -> None:
    job = payload.get("job") or {}
    prefix = f"auto_video/lipsync/{_safe_name(str(job.get('id') or job.get('shot_id') or 'job'))}"
    _set_input(workflow, args.video_node, args.video_input, uploaded_video)
    _set_input(workflow, args.audio_node, args.audio_input, uploaded_audio)
    if args.seed_node:
        _set_input(workflow, args.seed_node, args.seed_input, args.seed)
    if args.output_node:
        _set_input(workflow, args.output_node, args.filename_prefix_input, prefix)
    if args.steps is not None:
        for node in args.steps_node:
            _set_input(workflow, node, args.steps_input, args.steps)
    if args.guidance_scale is not None:
        for node in args.steps_node:
            _set_input(workflow, node, args.cfg_input, args.guidance_scale)


if __name__ == "__main__":
    raise SystemExit(main())
