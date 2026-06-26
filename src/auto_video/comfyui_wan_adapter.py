from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_NEGATIVE = "blurry, low quality, distorted, watermark, static, no motion"


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
    parser = argparse.ArgumentParser(description="ComfyUI Wan adapter for auto-video external_command providers")
    parser.add_argument("--base-url")
    parser.add_argument("--base-url-env")
    parser.add_argument("--workflow")
    parser.add_argument("--workflow-env")
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--steps", type=int)
    parser.add_argument("--guidance-scale", type=float)
    parser.add_argument("--resolution", type=int)
    parser.add_argument("--prompt-node", default="257")
    parser.add_argument("--prompt-input", default="value")
    parser.add_argument("--negative-node", default="218")
    parser.add_argument("--negative-input", default="text")
    parser.add_argument("--image-node", default="224")
    parser.add_argument("--image-input", default="image")
    parser.add_argument("--seed-node", default="231")
    parser.add_argument("--seed-input", default="seed")
    parser.add_argument("--duration-node", default="238")
    parser.add_argument("--duration-input", default="value")
    parser.add_argument("--resolution-node", default="248")
    parser.add_argument("--resolution-input", default="value")
    parser.add_argument("--video-node", default="230")
    parser.add_argument("--frame-rate-input", default="frame_rate")
    parser.add_argument("--filename-prefix-input", default="filename_prefix")
    parser.add_argument("--steps-node", action="append", default=["228", "229"])
    parser.add_argument("--steps-input", default="steps")
    parser.add_argument("--cfg-input", default="cfg")
    parser.add_argument("--job", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--output", required=True)
    return parser


def run(args: argparse.Namespace) -> None:
    base_url = _base_url(args).rstrip("/")
    workflow_path = _workflow_path(args)
    payload = json.loads(Path(args.job).read_text(encoding="utf-8"))
    output = Path(args.output)
    image_path = _first_image_reference(payload)
    if image_path is None:
        raise RuntimeError("ComfyUI Wan adapter requires an existing image reference")

    uploaded = _upload_image(base_url, image_path, timeout=args.timeout)
    workflow = _load_workflow(workflow_path)
    _patch_workflow(workflow, payload, args, uploaded_image=uploaded["name"])
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
                "output": output.as_posix(),
            },
            ensure_ascii=False,
        )
    )


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


def _load_workflow(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError(f"workflow {path.as_posix()} must be a JSON object")
    prompt = {
        key: value
        for key, value in raw.items()
        if isinstance(value, dict) and isinstance(value.get("inputs"), dict) and "class_type" in value
    }
    if not prompt:
        raise RuntimeError(f"workflow {path.as_posix()} does not contain ComfyUI API nodes")
    return prompt


def _patch_workflow(
    workflow: dict[str, Any],
    payload: dict[str, Any],
    args: argparse.Namespace,
    *,
    uploaded_image: str,
) -> None:
    job = payload.get("job") or {}
    controls = job.get("controls") or {}
    prompt = str(job.get("prompt") or "")
    negative_prompt = str(job.get("negative_prompt") or controls.get("negative_prompt") or DEFAULT_NEGATIVE)
    duration = _duration_seconds(job)
    resolution = args.resolution or max(_int_value(controls.get("width"), 832), _int_value(controls.get("height"), 480))
    fps = _int_value(controls.get("fps"), 16)
    prefix = f"auto_video/{_safe_name(str(job.get('id') or job.get('shot_id') or 'job'))}"

    _set_input(workflow, args.image_node, args.image_input, uploaded_image)
    _set_input(workflow, args.prompt_node, args.prompt_input, prompt)
    _set_input(workflow, args.negative_node, args.negative_input, negative_prompt)
    _set_input(workflow, args.seed_node, args.seed_input, args.seed)
    _set_input(workflow, args.duration_node, args.duration_input, duration)
    _set_input(workflow, args.resolution_node, args.resolution_input, resolution)
    _set_input(workflow, args.video_node, args.frame_rate_input, fps)
    _set_input(workflow, args.video_node, args.filename_prefix_input, prefix)

    if args.steps is not None:
        for node in args.steps_node:
            _set_input(workflow, node, args.steps_input, args.steps)
    if args.guidance_scale is not None:
        for node in args.steps_node:
            _set_input(workflow, node, args.cfg_input, args.guidance_scale)


def _set_input(workflow: dict[str, Any], node: str, name: str, value: Any) -> None:
    if node not in workflow:
        return
    inputs = workflow[node].setdefault("inputs", {})
    if isinstance(inputs, dict):
        inputs[name] = value


def _upload_image(base_url: str, image_path: Path, *, timeout: float) -> dict[str, Any]:
    boundary = f"----auto-video-{uuid.uuid4().hex}"
    body = _multipart_body(
        boundary,
        fields={"type": "input", "overwrite": "true"},
        files={"image": (image_path.name, image_path.read_bytes(), "application/octet-stream")},
    )
    request = Request(
        f"{base_url}/upload/image",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    return _request_json(request, timeout=timeout)


def _queue_prompt(base_url: str, prompt: dict[str, Any], *, timeout: float) -> str:
    data = json.dumps({"prompt": prompt, "client_id": str(uuid.uuid4())}, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{base_url}/prompt",
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    payload = _request_json(request, timeout=timeout)
    prompt_id = payload.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI did not return prompt_id: {payload}")
    return str(prompt_id)


def _wait_for_media(base_url: str, prompt_id: str, *, timeout: float, poll_interval: float) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() <= deadline:
        request = Request(f"{base_url}/history/{prompt_id}", headers={"Accept": "application/json"}, method="GET")
        payload = _request_json(request, timeout=min(30, timeout))
        media = _first_media(payload, prompt_id)
        if media:
            return media
        time.sleep(max(0.01, poll_interval))
    raise RuntimeError(f"ComfyUI prompt {prompt_id} did not finish within {timeout:g} seconds")


def _first_media(history: dict[str, Any], prompt_id: str) -> dict[str, str] | None:
    prompt_history = history.get(prompt_id)
    if not isinstance(prompt_history, dict):
        return None
    outputs = prompt_history.get("outputs")
    if not isinstance(outputs, dict):
        return None
    for node_output in outputs.values():
        if not isinstance(node_output, dict):
            continue
        for key in ("gifs", "videos", "images"):
            values = node_output.get(key)
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, dict) or "filename" not in value:
                    continue
                return {
                    "filename": str(value.get("filename", "")),
                    "subfolder": str(value.get("subfolder", "")),
                    "type": str(value.get("type", "output")),
                }
    return None


def _download_media(base_url: str, media: dict[str, str], *, timeout: float) -> bytes:
    query = urlencode(
        {
            "filename": media["filename"],
            "subfolder": media.get("subfolder", ""),
            "type": media.get("type", "output"),
        }
    )
    request = Request(f"{base_url}/view?{query}", method="GET")
    return _request_bytes(request, timeout=timeout)


def _request_json(request: Request, *, timeout: float) -> dict[str, Any]:
    body = _request_bytes(request, timeout=timeout)
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ComfyUI returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"ComfyUI returned non-object JSON: {payload!r}")
    return payload


def _request_bytes(request: Request, *, timeout: float) -> bytes:
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ComfyUI HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"ComfyUI request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"ComfyUI request timed out after {timeout:g} seconds") from exc


def _multipart_body(
    boundary: str,
    *,
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
) -> bytes:
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    for name, (filename, body, content_type) in files.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                (
                    f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                    f"Content-Type: {content_type}\r\n\r\n"
                ).encode("utf-8"),
                body,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks)


def _first_image_reference(payload: dict[str, Any]) -> Path | None:
    for ref in payload.get("references", []):
        if ref.get("type") != "image" or not ref.get("exists", False):
            continue
        absolute_path = ref.get("absolute_path")
        if not absolute_path:
            continue
        path = Path(str(absolute_path))
        if path.exists():
            return path
    return None


def _duration_seconds(job: dict[str, Any]) -> int:
    duration = job.get("duration")
    if duration is None:
        return 5
    try:
        return max(1, math.ceil(float(duration)))
    except (TypeError, ValueError):
        return 5


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return safe or "job"


if __name__ == "__main__":
    raise SystemExit(main())
