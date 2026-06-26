from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any, Sequence

from .errors import AutoVideoError
from .remote_transport import (
    CommandResult,
    CommandRunner,
    _ssh_option_args,
    _validate_command_token,
    _validate_host,
    _validate_option_values,
    _validate_remote_dir,
)

SNIPPET_LIMIT = 500


@dataclass(frozen=True)
class RemoteDoctorOptions:
    host: str
    remote_dir: str
    remote_auto_video: str = "auto-video"
    ssh_options: tuple[str, ...] = ()


@dataclass(frozen=True)
class DoctorCheckPlan:
    name: str
    commands: tuple[tuple[str, ...], ...]
    planned_message: str
    success_message: str
    failure_message: str
    fix: str


@dataclass(frozen=True)
class RemoteDoctorPlan:
    host: str
    remote_dir: str
    checks: tuple[DoctorCheckPlan, ...]


@dataclass(frozen=True)
class DoctorCheckRecord:
    name: str
    status: str
    commands: tuple[tuple[str, ...], ...]
    message: str
    fix: str | None = None
    returncode: int | None = None
    stdout: str | None = None
    stderr: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "command": _format_commands(self.commands),
            "message": self.message,
            "fix": self.fix,
        }
        if self.returncode is not None:
            payload["returncode"] = self.returncode
        if self.stdout:
            payload["stdout"] = self.stdout
        if self.stderr:
            payload["stderr"] = self.stderr
        return payload


class SubprocessDoctorCommandRunner:
    def run(self, command: Sequence[str]) -> CommandResult:
        command_tuple = tuple(command)
        try:
            completed = subprocess.run(list(command_tuple), check=False, capture_output=True, text=True)
        except FileNotFoundError:
            return CommandResult(
                command=command_tuple,
                returncode=127,
                stderr=f"missing command {command_tuple[0]!r}",
            )
        return CommandResult(
            command=command_tuple,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def build_remote_doctor_plan(options: RemoteDoctorOptions) -> RemoteDoctorPlan:
    _validate_host(options.host)
    _validate_remote_dir(options.remote_dir)
    _validate_command_token("remote-auto-video", options.remote_auto_video)
    _validate_option_values("ssh-option", options.ssh_options)

    host = options.host
    remote_dir = options.remote_dir.rstrip("/")
    ssh_prefix = ("ssh", *_ssh_option_args(options.ssh_options), host)
    checks = (
        DoctorCheckPlan(
            name="local_ssh",
            commands=(("ssh", "-V"),),
            planned_message="planned local ssh availability check",
            success_message="local ssh command is available",
            failure_message="local ssh command is not available",
            fix="Install OpenSSH client locally or update PATH.",
        ),
        DoctorCheckPlan(
            name="local_rsync",
            commands=(("rsync", "--version"),),
            planned_message="planned local rsync availability check",
            success_message="local rsync command is available",
            failure_message="local rsync command is not available",
            fix="Install rsync locally or update PATH.",
        ),
        DoctorCheckPlan(
            name="ssh_connectivity",
            commands=((*ssh_prefix, "true"),),
            planned_message="planned ssh connectivity check",
            success_message="ssh connection succeeded",
            failure_message="ssh connection failed",
            fix="Verify host, key, username, port, and --ssh-option values.",
        ),
        DoctorCheckPlan(
            name="remote_rsync",
            commands=((*ssh_prefix, "command", "-v", "rsync"),),
            planned_message="planned remote rsync availability check",
            success_message="remote rsync command is available",
            failure_message="remote rsync command was not found",
            fix="Install rsync on the remote host.",
        ),
        DoctorCheckPlan(
            name="remote_auto_video",
            commands=((*ssh_prefix, options.remote_auto_video, "--help"),),
            planned_message="planned remote auto-video availability check",
            success_message="remote auto-video command is callable",
            failure_message="remote auto-video command was not callable",
            fix="Install the project on the remote host or pass --remote-auto-video.",
        ),
        DoctorCheckPlan(
            name="remote_worker_cli",
            commands=((*ssh_prefix, options.remote_auto_video, "worker", "run", "--help"),),
            planned_message="planned remote worker CLI check",
            success_message="remote worker CLI is available",
            failure_message="remote worker CLI was not available",
            fix="Update the remote project version so it exposes worker run.",
        ),
        DoctorCheckPlan(
            name="remote_dir_writable",
            commands=(
                (*ssh_prefix, "mkdir", "-p", remote_dir),
                (*ssh_prefix, "test", "-w", remote_dir),
            ),
            planned_message="planned remote directory writability check",
            success_message="remote directory exists and is writable",
            failure_message="remote directory was not writable",
            fix="Create the directory with proper permissions or choose another --remote-dir.",
        ),
    )
    return RemoteDoctorPlan(host=host, remote_dir=remote_dir, checks=checks)


def run_remote_doctor(
    options: RemoteDoctorOptions,
    *,
    runner: CommandRunner | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    plan = build_remote_doctor_plan(options)
    if dry_run:
        records = [
            DoctorCheckRecord(
                name=check.name,
                status="planned",
                commands=check.commands,
                message=check.planned_message,
            )
            for check in plan.checks
        ]
        return _report(plan, records, dry_run=True)

    command_runner = runner or SubprocessDoctorCommandRunner()
    records = [_run_check(check, command_runner) for check in plan.checks]
    return _report(plan, records, dry_run=False)


def _run_check(check: DoctorCheckPlan, runner: CommandRunner) -> DoctorCheckRecord:
    last_result: CommandResult | None = None
    for command in check.commands:
        try:
            result = runner.run(command)
        except AutoVideoError as exc:
            return DoctorCheckRecord(
                name=check.name,
                status="failed",
                commands=check.commands,
                message=check.failure_message,
                fix=check.fix,
                stderr=_snippet(str(exc)),
            )
        last_result = result
        if result.returncode != 0:
            return DoctorCheckRecord(
                name=check.name,
                status="failed",
                commands=check.commands,
                message=check.failure_message,
                fix=check.fix,
                returncode=result.returncode,
                stdout=_snippet(result.stdout),
                stderr=_snippet(result.stderr),
            )

    return DoctorCheckRecord(
        name=check.name,
        status="ok",
        commands=check.commands,
        message=check.success_message,
        stdout=_snippet(last_result.stdout if last_result else ""),
        stderr=_snippet(last_result.stderr if last_result else ""),
    )


def _report(plan: RemoteDoctorPlan, records: list[DoctorCheckRecord], *, dry_run: bool) -> dict[str, Any]:
    return {
        "ok": all(record.status != "failed" for record in records),
        "dry_run": dry_run,
        "host": plan.host,
        "remote_dir": plan.remote_dir,
        "checks": [record.to_dict() for record in records],
    }


def _format_commands(commands: tuple[tuple[str, ...], ...]) -> list[str] | list[list[str]]:
    if len(commands) == 1:
        return list(commands[0])
    return [list(command) for command in commands]


def _snippet(value: str) -> str | None:
    stripped = value.strip()
    if not stripped:
        return None
    if len(stripped) <= SNIPPET_LIMIT:
        return stripped
    return stripped[: SNIPPET_LIMIT - 3] + "..."
