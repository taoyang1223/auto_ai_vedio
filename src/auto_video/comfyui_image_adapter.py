from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .comfyui_wan_adapter import (
    _base_url,
    _download_media,
    _int_value,
    _load_workflow,
    _queue_prompt,
    _safe_name,
    _set_input,
    _wait_for_media,
    _workflow_path,
)

DEFAULT_NEGATIVE = "text, watermark, logo, low quality, blurry, distorted anatomy, extra fingers"


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
    parser = argparse.ArgumentParser(description="ComfyUI text-to-image adapter for auto-video first frames")
    parser.add_argument("--base-url")
    parser.add_argument("--base-url-env")
    parser.add_argument("--workflow")
    parser.add_argument("--workflow-env")
    parser.add_argument("--workflow-profile")
    parser.add_argument("--workflow-profile-env")
    parser.add_argument("--timeout", type=float, default=1200)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--steps", type=int)
    parser.add_argument("--guidance-scale", type=float)
    parser.add_argument("--prompt-node", default="187")
    parser.add_argument("--prompt-input", default="text")
    parser.add_argument("--negative-node", default="437")
    parser.add_argument("--negative-input", default="text")
    parser.add_argument("--seed-node", default="3")
    parser.add_argument("--seed-input", default="seed")
    parser.add_argument("--size-node", default="118")
    parser.add_argument("--width-input", default="width")
    parser.add_argument("--height-input", default="height")
    parser.add_argument("--output-node", default="499")
    parser.add_argument("--filename-prefix-input", default="filename_prefix")
    parser.add_argument("--steps-node", action="append", default=["3"])
    parser.add_argument("--steps-input", default="steps")
    parser.add_argument("--cfg-input", default="cfg")
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

    workflow = _load_workflow(workflow_path)
    _patch_workflow(workflow, payload, args)
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


def _apply_workflow_profile(args: argparse.Namespace) -> None:
    profile_name = args.workflow_profile
    if not profile_name and args.workflow_profile_env:
        profile_name = os.environ.get(args.workflow_profile_env)
    if not profile_name:
        return
    from .project import load_project
    from .workflow_registry import comfyui_image_adapter_options

    project = load_project(args.project_root)
    for key, value in comfyui_image_adapter_options(project, profile_name).items():
        if key in {"base_url", "base_url_env", "workflow", "workflow_env"} and getattr(args, key, None):
            continue
        setattr(args, key, value)


def _patch_workflow(workflow: dict[str, Any], payload: dict[str, Any], args: argparse.Namespace) -> None:
    job = payload.get("job") or {}
    controls = job.get("controls") or {}
    prompt = str(job.get("prompt") or "")
    negative_prompt = str(job.get("negative_prompt") or controls.get("negative_prompt") or DEFAULT_NEGATIVE)
    width = _int_value(controls.get("width"), 1024)
    height = _int_value(controls.get("height"), 1024)
    prefix = f"auto_video/first_frames/{_safe_name(str(job.get('id') or job.get('shot_id') or 'image'))}"

    _set_input(workflow, args.prompt_node, args.prompt_input, prompt)
    _set_input(workflow, args.negative_node, args.negative_input, negative_prompt)
    _set_input(workflow, args.seed_node, args.seed_input, args.seed)
    _set_input(workflow, args.size_node, args.width_input, width)
    _set_input(workflow, args.size_node, args.height_input, height)
    _set_input(workflow, args.output_node, args.filename_prefix_input, prefix)

    if args.steps is not None:
        for node in args.steps_node:
            _set_input(workflow, node, args.steps_input, args.steps)
    if args.guidance_scale is not None:
        for node in args.steps_node:
            _set_input(workflow, node, args.cfg_input, args.guidance_scale)


if __name__ == "__main__":
    raise SystemExit(main())
