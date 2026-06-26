#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

I2V_NEGATIVE = "blurry, low quality, distorted, watermark, static, no motion"
T2V_NEGATIVE = "blurry, low quality, distorted, watermark"


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
    parser = argparse.ArgumentParser(description="Wan HTTP adapter for auto-video external_command providers")
    parser.add_argument("--base-url")
    parser.add_argument("--base-url-env")
    parser.add_argument("--token-env")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--frames", type=int)
    parser.add_argument("--steps", type=int, default=24)
    parser.add_argument("--guidance-scale", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--job", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--output", required=True)
    return parser


def run(args: argparse.Namespace) -> None:
    base_url = _base_url(args).rstrip("/")
    token = os.environ.get(args.token_env, "") if args.token_env else ""
    payload = json.loads(Path(args.job).read_text(encoding="utf-8"))
    output = Path(args.output)

    image_path = _first_image_reference(payload)
    endpoint = "i2v" if image_path else "t2v"
    request_body = _wan_payload(payload, args, image_path=image_path)
    response_body = _post_json(
        f"{base_url}/{endpoint}",
        request_body,
        token=token,
        timeout=args.timeout,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(response_body)
    print(json.dumps({"endpoint": endpoint, "output": output.as_posix()}, ensure_ascii=False))


def _base_url(args: argparse.Namespace) -> str:
    if args.base_url:
        return args.base_url
    if args.base_url_env:
        value = os.environ.get(args.base_url_env)
        if value:
            return value
        raise RuntimeError(f"environment variable {args.base_url_env} is not set")
    raise RuntimeError("Wan base URL is required; pass --base-url or --base-url-env")


def _wan_payload(payload: dict[str, Any], args: argparse.Namespace, *, image_path: Path | None) -> dict[str, Any]:
    job = payload.get("job") or {}
    controls = job.get("controls") or {}
    fps = _int_value(controls.get("fps"), default=16)
    body: dict[str, Any] = {
        "prompt": str(job.get("prompt") or ""),
        "negative_prompt": str(job.get("negative_prompt") or (I2V_NEGATIVE if image_path else T2V_NEGATIVE)),
        "num_frames": args.frames or _frames_from_job(job, fps),
        "guidance_scale": args.guidance_scale,
        "num_inference_steps": args.steps,
        "seed": args.seed,
        "width": _int_value(controls.get("width"), default=832),
        "height": _int_value(controls.get("height"), default=480),
        "fps": fps,
    }
    if image_path:
        body["image_base64"] = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return body


def _frames_from_job(job: dict[str, Any], fps: int) -> int:
    duration = job.get("duration")
    if duration is None:
        return 33
    try:
        return max(1, round(float(duration) * fps))
    except (TypeError, ValueError):
        return 33


def _int_value(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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


def _post_json(url: str, body: dict[str, Any], *, token: str, timeout: int) -> bytes:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "Accept": "video/mp4, application/json",
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=data, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            response_body = response.read()
            content_type = response.headers.get("Content-Type", "")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Wan HTTP {exc.code}: {error_body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Wan request failed: {exc.reason}") from exc

    if "application/json" in content_type:
        text = response_body.decode("utf-8", errors="replace")
        raise RuntimeError(f"Wan returned JSON error: {text}")
    return response_body


if __name__ == "__main__":
    raise SystemExit(main())
