from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> int:
    args = build_parser().parse_args()
    report = run(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ComfyUI runtime preflight doctor")
    parser.add_argument("--base-url")
    parser.add_argument("--base-url-env")
    parser.add_argument("--workflow")
    parser.add_argument("--workflow-env")
    parser.add_argument("--mode", choices=["wan_video", "image", "lipsync"], default="wan_video")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--require-gpu", action="store_true")
    parser.add_argument("--require-idle", action="store_true")
    parser.add_argument("--image-node", default="224")
    parser.add_argument("--image-input", default="image")
    parser.add_argument("--prompt-node", default="257")
    parser.add_argument("--prompt-input", default="value")
    parser.add_argument("--negative-node", default="218")
    parser.add_argument("--negative-input", default="text")
    parser.add_argument("--seed-node", default="231")
    parser.add_argument("--seed-input", default="seed")
    parser.add_argument("--duration-node", default="238")
    parser.add_argument("--duration-input", default="value")
    parser.add_argument("--resolution-node", default="248")
    parser.add_argument("--resolution-input", default="value")
    parser.add_argument("--size-node", default="118")
    parser.add_argument("--width-input", default="width")
    parser.add_argument("--height-input", default="height")
    parser.add_argument("--output-node", default="499")
    parser.add_argument("--video-node", default="230")
    parser.add_argument("--video-input", default="video")
    parser.add_argument("--audio-node", default="audio")
    parser.add_argument("--audio-input", default="audio")
    parser.add_argument("--frame-rate-input", default="frame_rate")
    parser.add_argument("--filename-prefix-input", default="filename_prefix")
    parser.add_argument("--steps-node", action="append", default=["228", "229"])
    parser.add_argument("--steps-input", default="steps")
    parser.add_argument("--cfg-input", default="cfg")
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    base_url, base_url_check = _resolve_base_url(args)
    workflow_path, workflow_path_check = _resolve_workflow_path(args)
    checks = [base_url_check, workflow_path_check]

    if base_url:
        system_stats = _fetch_json_check(base_url, "/system_stats", name="system_stats", timeout=args.timeout)
        checks.append(system_stats)
        if args.require_gpu:
            checks.append(_gpu_check(system_stats.get("details", {})))
        queue = _fetch_json_check(base_url, "/queue", name="queue", timeout=args.timeout)
        checks.append(queue)
        if args.require_idle:
            checks.append(_idle_check(queue.get("details", {})))

    if workflow_path:
        checks.append(_workflow_check(workflow_path, args))

    return _report(base_url, workflow_path.as_posix() if workflow_path else "", checks)


def _resolve_base_url(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    if args.base_url:
        return args.base_url.rstrip("/"), _check("base_url", "ok", "base URL provided")
    if args.base_url_env:
        value = os.environ.get(args.base_url_env, "")
        if value:
            return value.rstrip("/"), _check("base_url", "ok", f"base URL read from {args.base_url_env}")
        return "", _check(
            "base_url",
            "failed",
            f"environment variable {args.base_url_env} is not set",
            fix="Set the environment variable or pass --base-url.",
        )
    return "", _check("base_url", "failed", "base URL is required", fix="Pass --base-url or --base-url-env.")


def _resolve_workflow_path(args: argparse.Namespace) -> tuple[Path | None, dict[str, Any]]:
    if args.workflow:
        return Path(args.workflow), _check("workflow_path", "ok", "workflow path provided")
    if args.workflow_env:
        value = os.environ.get(args.workflow_env, "")
        if value:
            return Path(value), _check("workflow_path", "ok", f"workflow path read from {args.workflow_env}")
        return None, _check(
            "workflow_path",
            "failed",
            f"environment variable {args.workflow_env} is not set",
            fix="Set the environment variable or pass --workflow.",
        )
    return None, _check(
        "workflow_path",
        "failed",
        "workflow path is required",
        fix="Pass --workflow or --workflow-env.",
    )


def _fetch_json_check(base_url: str, path: str, *, name: str, timeout: float) -> dict[str, Any]:
    request = Request(f"{base_url}{path}", headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return _check(name, "failed", f"ComfyUI {path} returned HTTP {exc.code}", fix=body or "Check ComfyUI logs.")
    except URLError as exc:
        return _check(
            name,
            "failed",
            f"ComfyUI {path} request failed: {exc.reason}",
            fix="Check base URL, SSH access, and whether ComfyUI is running.",
        )
    except TimeoutError:
        return _check(
            name,
            "failed",
            f"ComfyUI {path} request timed out after {timeout:g} seconds",
            fix="Check service load, model startup, and network connectivity.",
        )
    try:
        details = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        return _check(name, "failed", f"ComfyUI {path} JSON could not be parsed: {exc}", fix="Check response body.")
    if not isinstance(details, dict):
        return _check(name, "failed", f"ComfyUI {path} returned non-object JSON", details={"value": details})
    return _check(name, "ok", f"ComfyUI {path} responded", details=details)


def _gpu_check(system_stats: dict[str, Any]) -> dict[str, Any]:
    devices = system_stats.get("devices")
    if not isinstance(devices, list):
        return _check("gpu", "failed", "ComfyUI system stats did not include devices", fix="Check ComfyUI startup logs.")
    gpu_devices = [
        device
        for device in devices
        if isinstance(device, dict) and any(token in str(device.get("type", "")).lower() for token in ("cuda", "gpu"))
    ]
    if gpu_devices:
        return _check("gpu", "ok", "ComfyUI reports a GPU device", details={"devices": gpu_devices})
    return _check("gpu", "failed", "ComfyUI did not report a GPU device", fix="Start ComfyUI with CUDA available.")


def _idle_check(queue: dict[str, Any]) -> dict[str, Any]:
    running = queue.get("queue_running") if isinstance(queue.get("queue_running"), list) else []
    pending = queue.get("queue_pending") if isinstance(queue.get("queue_pending"), list) else []
    if running or pending:
        return _check(
            "queue_idle",
            "failed",
            f"ComfyUI queue is busy: {len(running)} running, {len(pending)} pending",
            fix="Wait for current jobs to finish or omit --require-idle.",
            details={"running": len(running), "pending": len(pending)},
        )
    return _check("queue_idle", "ok", "ComfyUI queue is idle", details={"running": 0, "pending": 0})


def _workflow_check(path: Path, args: argparse.Namespace) -> dict[str, Any]:
    if not path.exists():
        return _check("workflow", "failed", f"workflow {path.as_posix()} does not exist", fix="Use the correct workflow path.")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return _check("workflow", "failed", f"workflow JSON could not be parsed: {exc}", fix="Export ComfyUI API JSON.")
    if not isinstance(raw, dict):
        return _check("workflow", "failed", f"workflow {path.as_posix()} must be a JSON object")

    workflow = {
        key: value
        for key, value in raw.items()
        if isinstance(value, dict) and isinstance(value.get("inputs"), dict) and "class_type" in value
    }
    if not workflow:
        return _check("workflow", "failed", "workflow does not contain ComfyUI API nodes", fix="Export API-format JSON.")

    required = _required_inputs(args)
    missing: list[str] = []
    for label, (node, input_name) in required.items():
        inputs = workflow.get(node, {}).get("inputs")
        if not isinstance(inputs, dict):
            missing.append(f"{label}: node {node}")
        elif input_name not in inputs:
            missing.append(f"{label}: node {node} input {input_name}")

    optional_missing: list[str] = []
    for node in _steps_nodes(args):
        inputs = workflow.get(str(node), {}).get("inputs")
        if not isinstance(inputs, dict):
            optional_missing.append(f"steps node {node}")
            continue
        for input_name in (args.steps_input, args.cfg_input):
            if input_name not in inputs:
                optional_missing.append(f"steps node {node} input {input_name}")

    details = {
        "node_count": len(workflow),
        "required": required,
        "optional_missing": optional_missing,
    }
    if missing:
        return _check(
            "workflow",
            "failed",
            "workflow is missing required adapter nodes or inputs",
            fix="Pass matching --*-node/--*-input options or choose the matching ComfyUI API workflow.",
            details={**details, "missing": missing},
        )
    if optional_missing:
        return _check(
            "workflow",
            "warning",
            "workflow is usable, but some optional steps/cfg inputs were not found",
            details=details,
        )
    return _check("workflow", "ok", "workflow contains required ComfyUI adapter nodes", details=details)


def _required_inputs(args: argparse.Namespace) -> dict[str, tuple[str, str]]:
    if args.mode == "image":
        return {
            "prompt": (_image_default(args.prompt_node, "257", "187"), _image_default(args.prompt_input, "value", "text")),
            "negative": (_image_default(args.negative_node, "218", "437"), args.negative_input),
            "seed": (_image_default(args.seed_node, "231", "3"), args.seed_input),
            "width": (args.size_node, args.width_input),
            "height": (args.size_node, args.height_input),
            "image_filename_prefix": (args.output_node, args.filename_prefix_input),
        }
    if args.mode == "lipsync":
        return {
            "source_video": (args.video_node, args.video_input),
            "source_audio": (args.audio_node, args.audio_input),
            "lipsync_filename_prefix": (args.output_node, args.filename_prefix_input),
        }
    return {
        "image": (args.image_node, args.image_input),
        "prompt": (args.prompt_node, args.prompt_input),
        "negative": (args.negative_node, args.negative_input),
        "seed": (args.seed_node, args.seed_input),
        "duration": (args.duration_node, args.duration_input),
        "resolution": (args.resolution_node, args.resolution_input),
        "video_frame_rate": (args.video_node, args.frame_rate_input),
        "video_filename_prefix": (args.video_node, args.filename_prefix_input),
    }


def _steps_nodes(args: argparse.Namespace) -> list[str]:
    if args.mode == "image" and args.steps_node == ["228", "229"]:
        return ["3"]
    return [str(node) for node in args.steps_node]


def _image_default(value: str, wan_default: str, image_default: str) -> str:
    return image_default if value == wan_default else value


def _check(
    name: str,
    status: str,
    message: str,
    *,
    fix: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name, "status": status, "message": message}
    if fix:
        payload["fix"] = fix
    if details is not None:
        payload["details"] = details
    return payload


def _report(base_url: str, workflow: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": all(check["status"] != "failed" for check in checks),
        "base_url": base_url,
        "workflow": workflow,
        "checks": checks,
    }


if __name__ == "__main__":
    raise SystemExit(main())
