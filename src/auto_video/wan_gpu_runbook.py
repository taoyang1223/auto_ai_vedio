from __future__ import annotations

import argparse
import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .remote_transport import (
    _reject_unsafe_token,
    _ssh_option_args,
    _validate_host,
    _validate_option_values,
    _validate_remote_dir,
)
from .wan_remote_smoke import WanRemoteSmokeOptions, build_wan_remote_smoke_plan

DEFAULT_REPO_URL = "https://github.com/taoyang1223/auto_ai_vedio.git"
DEFAULT_REMOTE_REPO_DIR = "/opt/auto-ai-video"
DEFAULT_WAN_BASE_URL = "http://127.0.0.1:8082"


@dataclass(frozen=True)
class WanGpuRunbookOptions:
    project: Path
    host: str
    remote_dir: str
    wan_base_url: str = DEFAULT_WAN_BASE_URL
    wan_base_url_env: str = "WAN_BASE_URL"
    wan_token_env: str | None = None
    provider: str = "wan_http"
    kind: str = "video"
    only: str | None = None
    local_dir: Path | None = None
    repo_url: str = DEFAULT_REPO_URL
    remote_repo_dir: str = DEFAULT_REMOTE_REPO_DIR
    remote_python: str | None = None
    remote_auto_video: str | None = None
    wan_start_command: str | None = None
    wan_log_path: str = "/tmp/wan_server.log"
    require_i2v: bool = True
    require_t2v: bool = False
    ssh_options: tuple[str, ...] = ()


def build_wan_gpu_runbook(options: WanGpuRunbookOptions) -> dict[str, Any]:
    _validate_options(options)
    remote_repo_dir = options.remote_repo_dir.rstrip("/")
    remote_python = options.remote_python or f"{remote_repo_dir}/.venv/bin/python"
    remote_auto_video = options.remote_auto_video or f"{remote_repo_dir}/.venv/bin/auto-video"
    smoke = build_wan_remote_smoke_plan(
        WanRemoteSmokeOptions(
            project=options.project,
            host=options.host,
            remote_dir=options.remote_dir,
            wan_base_url=options.wan_base_url,
            wan_base_url_env=options.wan_base_url_env,
            wan_token_env=options.wan_token_env,
            provider=options.provider,
            kind=options.kind,
            only=options.only,
            local_dir=options.local_dir,
            remote_auto_video=remote_auto_video,
            remote_python=remote_python,
            require_i2v=options.require_i2v,
            require_t2v=options.require_t2v,
            ssh_options=options.ssh_options,
        )
    )
    phases = [
        _manual_phase(
            "rent_gpu",
            "Rent or start a GPU host with SSH access, enough VRAM for the selected Wan model, git, python3, rsync, and nvidia-smi.",
        ),
        _command_phase(
            "install_auto_video",
            {
                "sync_and_install": [
                    _remote_shell(options, _install_script(options.repo_url, remote_repo_dir, remote_python))
                ],
                "gpu_status": [_ssh(options, "nvidia-smi")],
            },
            notes=[
                "Run this after the rented GPU host is reachable. It installs the package into a project-local venv.",
            ],
        ),
        _wan_start_phase(options),
        _command_phase(
            "preflight",
            {
                "remote_doctor": [tuple(smoke["commands"]["remote_doctor"])],
                "wan_runtime_doctor": [tuple(smoke["commands"]["wan_runtime_doctor"])],
            },
            notes=[
                "The Wan runtime doctor checks GET /health and required I2V/T2V capability flags before generation.",
            ],
        ),
        _command_phase(
            "generate",
            {"remote_run": [tuple(smoke["commands"]["remote_run"])]},
            notes=[
                "remote run exports the worker bundle, uploads it, runs the remote worker, downloads results, and imports them locally.",
            ],
        ),
        _manual_phase(
            "collect",
            "Inspect local manifest and generated clips after remote run finishes. The download/import step is part of remote run.",
        ),
        _manual_phase(
            "shutdown",
            "Stop or release the rented GPU machine after outputs are verified, because most providers bill while the instance is running.",
        ),
    ]
    return {
        "dry_run": True,
        "project": options.project.as_posix(),
        "host": options.host,
        "remote_dir": options.remote_dir.rstrip("/"),
        "remote_repo_dir": remote_repo_dir,
        "remote_python": remote_python,
        "remote_auto_video": remote_auto_video,
        "wan_base_url_env": options.wan_base_url_env,
        "wan_base_url": options.wan_base_url,
        "assumptions": [
            "The cloud GPU machine already exists and accepts SSH.",
            "The Wan HTTP service speaks GET /health and synchronous POST /i2v or /t2v.",
            "The remote worker calls Wan through the remote machine's loopback URL by default.",
        ],
        "phases": phases,
        "smoke": smoke,
    }


def format_runbook_markdown(runbook: dict[str, Any]) -> str:
    lines = [
        "# Wan GPU Runbook",
        "",
        f"- Project: `{runbook['project']}`",
        f"- Host: `{runbook['host']}`",
        f"- Remote job dir: `{runbook['remote_dir']}`",
        f"- Wan URL: `{runbook['wan_base_url_env']}={runbook['wan_base_url']}`",
        "",
        "## Assumptions",
        "",
    ]
    for assumption in runbook["assumptions"]:
        lines.append(f"- {assumption}")
    lines.append("")
    for index, phase in enumerate(runbook["phases"], start=1):
        lines.extend([f"## {index}. {phase['title']}", ""])
        if phase.get("manual_action"):
            lines.extend([phase["manual_action"], ""])
        for note in phase.get("notes", []):
            lines.extend([f"- {note}", ""])
        for label, commands in phase.get("commands", {}).items():
            lines.extend([f"### {label}", ""])
            for command in commands:
                lines.extend(["```bash", shlex.join(command), "```", ""])
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runbook = build_wan_gpu_runbook(
        WanGpuRunbookOptions(
            project=Path(args.project),
            host=args.host,
            remote_dir=args.remote_dir,
            wan_base_url=args.wan_base_url,
            wan_base_url_env=args.wan_base_url_env,
            wan_token_env=args.wan_token_env,
            provider=args.provider,
            kind=args.kind,
            only=args.only,
            local_dir=Path(args.local_dir) if args.local_dir else None,
            repo_url=args.repo_url,
            remote_repo_dir=args.remote_repo_dir,
            remote_python=args.remote_python,
            remote_auto_video=args.remote_auto_video,
            wan_start_command=args.wan_start_command,
            wan_log_path=args.wan_log_path,
            require_i2v=args.require_i2v,
            require_t2v=args.require_t2v,
            ssh_options=tuple(args.ssh_option),
        )
    )
    if args.format == "markdown":
        print(format_runbook_markdown(runbook), end="")
    else:
        print(json.dumps(runbook, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a rented GPU Wan runbook")
    parser.add_argument("--project", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--remote-dir", required=True)
    parser.add_argument("--wan-base-url", default=DEFAULT_WAN_BASE_URL)
    parser.add_argument("--wan-base-url-env", default="WAN_BASE_URL")
    parser.add_argument("--wan-token-env")
    parser.add_argument("--provider", default="wan_http")
    parser.add_argument("--kind", choices=["image", "video", "audio"], default="video")
    parser.add_argument("--only")
    parser.add_argument("--local-dir")
    parser.add_argument("--repo-url", default=DEFAULT_REPO_URL)
    parser.add_argument("--remote-repo-dir", default=DEFAULT_REMOTE_REPO_DIR)
    parser.add_argument("--remote-python")
    parser.add_argument("--remote-auto-video")
    parser.add_argument("--wan-start-command")
    parser.add_argument("--wan-log-path", default="/tmp/wan_server.log")
    parser.add_argument("--require-i2v", dest="require_i2v", action="store_true", default=True)
    parser.add_argument("--no-require-i2v", dest="require_i2v", action="store_false")
    parser.add_argument("--require-t2v", action="store_true")
    parser.add_argument("--ssh-option", action="append", default=[])
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    return parser


def _validate_options(options: WanGpuRunbookOptions) -> None:
    _validate_host(options.host)
    _validate_remote_dir(options.remote_dir)
    _validate_remote_dir(options.remote_repo_dir)
    _validate_option_values("ssh-option", options.ssh_options)
    _reject_unsafe_token("repo-url", options.repo_url)
    _reject_unsafe_token("wan-base-url", options.wan_base_url)
    _reject_unsafe_token("wan-base-url-env", options.wan_base_url_env)
    if options.wan_token_env:
        _reject_unsafe_token("wan-token-env", options.wan_token_env)
    if options.remote_python:
        _reject_unsafe_token("remote-python", options.remote_python)
    if options.remote_auto_video:
        _reject_unsafe_token("remote-auto-video", options.remote_auto_video)
    _reject_unsafe_token("wan-log-path", options.wan_log_path)


def _phase_name_to_title(name: str) -> str:
    special = {"gpu": "GPU", "http": "HTTP", "wan": "Wan"}
    return " ".join(special.get(part, part.title()) for part in name.split("_"))


def _manual_phase(name: str, action: str) -> dict[str, Any]:
    return {"name": name, "title": _phase_name_to_title(name), "manual_action": action}


def _command_phase(
    name: str,
    commands: dict[str, list[tuple[str, ...]]],
    *,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "title": _phase_name_to_title(name),
        "commands": {key: [list(command) for command in value] for key, value in commands.items()},
    }
    if notes:
        payload["notes"] = notes
    return payload


def _wan_start_phase(options: WanGpuRunbookOptions) -> dict[str, Any]:
    if not options.wan_start_command:
        return _manual_phase(
            "start_wan_http",
            "Start a Wan HTTP service on the GPU host that answers GET /health and POST /i2v or /t2v. "
            "Pass --wan-start-command to include the exact remote launch command in this runbook.",
        )
    return _command_phase(
        "start_wan_http",
        {"start": [_remote_shell(options, options.wan_start_command)]},
        notes=[
            f"After starting Wan, inspect logs with: ssh {options.host} tail -n 80 {options.wan_log_path}",
        ],
    )


def _ssh(options: WanGpuRunbookOptions, *remote_args: str) -> tuple[str, ...]:
    return ("ssh", *_ssh_option_args(options.ssh_options), options.host, *remote_args)


def _remote_shell(options: WanGpuRunbookOptions, script: str) -> tuple[str, ...]:
    return _ssh(options, "bash", "-lc", script)


def _install_script(repo_url: str, remote_repo_dir: str, remote_python: str) -> str:
    quoted_repo = shlex.quote(repo_url)
    quoted_dir = shlex.quote(remote_repo_dir)
    quoted_python = shlex.quote(remote_python)
    return "\n".join(
        [
            "set -euo pipefail",
            f"if [ -d {quoted_dir}/.git ]; then",
            f"  git -C {quoted_dir} pull --ff-only",
            "else",
            f"  git clone {quoted_repo} {quoted_dir}",
            "fi",
            f"python3 -m venv {quoted_dir}/.venv",
            f"{quoted_python} -m pip install -U pip",
            f"{quoted_python} -m pip install -e {quoted_dir}",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
