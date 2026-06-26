from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

from .remote_transport import CommandResult, _ssh_option_args


@dataclass(frozen=True)
class WanRemoteSmokeOptions:
    project: Path
    host: str
    remote_dir: str
    wan_base_url: str
    wan_base_url_env: str = "WAN_BASE_URL"
    wan_token_env: str | None = None
    provider: str = "wan_http"
    kind: str = "video"
    only: str | None = None
    local_dir: Path | None = None
    remote_auto_video: str = "auto-video"
    remote_python: str = "python"
    remote_wan_doctor: str = "scripts/wan_runtime_doctor.py"
    require_i2v: bool = False
    require_t2v: bool = False
    ssh_options: tuple[str, ...] = ()


class SmokeCommandRunner(Protocol):
    def run(self, command: Sequence[str]) -> CommandResult:
        ...


class SubprocessSmokeCommandRunner:
    def run(self, command: Sequence[str]) -> CommandResult:
        completed = subprocess.run(list(command), capture_output=True, text=True, check=False)
        return CommandResult(
            command=tuple(command),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def build_wan_remote_smoke_plan(options: WanRemoteSmokeOptions) -> dict[str, Any]:
    commands = _commands(options)
    return {
        "dry_run": True,
        "host": options.host,
        "remote_dir": options.remote_dir,
        "wan_base_url_env": options.wan_base_url_env,
        "provider": options.provider,
        "commands": {name: list(command) for name, command in commands.items()},
    }


def execute_wan_remote_smoke(
    options: WanRemoteSmokeOptions,
    *,
    runner: SmokeCommandRunner | None = None,
) -> dict[str, Any]:
    command_runner = runner or SubprocessSmokeCommandRunner()
    steps: list[dict[str, Any]] = []
    for name, command in _commands(options).items():
        result = command_runner.run(command)
        step = {
            "name": name,
            "status": "ok" if result.returncode == 0 else "failed",
            "command": list(command),
            "returncode": result.returncode,
        }
        if result.stdout:
            step["stdout"] = result.stdout.strip()
        if result.stderr:
            step["stderr"] = result.stderr.strip()
        steps.append(step)
        if result.returncode != 0:
            return {"ok": False, "steps": steps}
    return {"ok": True, "steps": steps}


def _commands(options: WanRemoteSmokeOptions) -> dict[str, tuple[str, ...]]:
    remote_doctor = (
        sys.executable,
        "-m",
        "auto_video",
        "remote",
        "doctor",
        "--host",
        options.host,
        "--remote-dir",
        options.remote_dir,
        *_repeat_options("--ssh-option", options.ssh_options),
    )
    wan_runtime_doctor = (
        "ssh",
        *_ssh_option_args(options.ssh_options),
        options.host,
        f"{options.wan_base_url_env}={options.wan_base_url}",
        options.remote_python,
        options.remote_wan_doctor,
        "--base-url-env",
        options.wan_base_url_env,
        *_optional_token_env(options.wan_token_env),
        *_required_capabilities(options),
    )
    remote_run = (
        sys.executable,
        "-m",
        "auto_video",
        "remote",
        "run",
        options.project.as_posix(),
        "--provider",
        options.provider,
        "--kind",
        options.kind,
        "--host",
        options.host,
        "--remote-dir",
        options.remote_dir,
        *_optional("--only", options.only),
        *_optional("--local-dir", options.local_dir.as_posix() if options.local_dir else None),
        *_optional(
            "--remote-auto-video",
            options.remote_auto_video if options.remote_auto_video != "auto-video" else None,
        ),
        *_repeat_options("--ssh-option", options.ssh_options),
        "--remote-env",
        f"{options.wan_base_url_env}={options.wan_base_url}",
    )
    return {
        "remote_doctor": tuple(remote_doctor),
        "wan_runtime_doctor": tuple(wan_runtime_doctor),
        "remote_run": tuple(remote_run),
    }


def _optional(name: str, value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return (name, value)


def _repeat_options(name: str, values: tuple[str, ...]) -> tuple[str, ...]:
    args: list[str] = []
    for value in values:
        args.extend([name, value])
    return tuple(args)


def _optional_token_env(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return ("--token-env", value)


def _required_capabilities(options: WanRemoteSmokeOptions) -> tuple[str, ...]:
    args: list[str] = []
    if options.require_i2v:
        args.append("--require-i2v")
    if options.require_t2v:
        args.append("--require-t2v")
    return tuple(args)
