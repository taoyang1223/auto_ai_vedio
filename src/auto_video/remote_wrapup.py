from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .remote_doctor import DoctorCheckPlan, DoctorCheckRecord, SubprocessDoctorCommandRunner, _run_check
from .remote_transport import (
    CommandRunner,
    _ssh_option_args,
    _validate_host,
    _validate_option_values,
    _validate_remote_dir,
)


@dataclass(frozen=True)
class RemoteWrapupOptions:
    host: str
    remote_dir: str
    ssh_options: tuple[str, ...] = ()
    comfyui_base_url: str = "http://127.0.0.1:6006"


@dataclass(frozen=True)
class RemoteWrapupPlan:
    host: str
    remote_dir: str
    checks: tuple[DoctorCheckPlan, ...]


def build_remote_wrapup_plan(options: RemoteWrapupOptions) -> RemoteWrapupPlan:
    _validate_host(options.host)
    _validate_remote_dir(options.remote_dir)
    _validate_option_values("ssh-option", options.ssh_options)

    host = options.host
    remote_dir = options.remote_dir.rstrip("/")
    ssh_prefix = ("ssh", *_ssh_option_args(options.ssh_options), host)
    queue_url = f"{options.comfyui_base_url.rstrip('/')}/queue"
    checks = (
        DoctorCheckPlan(
            name="remote_job_dir_size",
            commands=((*ssh_prefix, "du", "-sh", remote_dir),),
            planned_message="planned remote job directory size check",
            success_message="remote job directory size collected",
            failure_message="could not inspect remote job directory size",
            fix="Check the remote directory path and permissions.",
        ),
        DoctorCheckPlan(
            name="remote_disk_free",
            commands=((*ssh_prefix, "df", "-h", remote_dir),),
            planned_message="planned remote disk free check",
            success_message="remote disk free collected",
            failure_message="could not inspect remote disk free",
            fix="Check whether the remote directory exists.",
        ),
        DoctorCheckPlan(
            name="comfyui_queue",
            commands=((*ssh_prefix, "curl", "-fsS", queue_url),),
            planned_message="planned ComfyUI queue check",
            success_message="ComfyUI queue collected",
            failure_message="could not inspect ComfyUI queue",
            fix="Check whether ComfyUI is running or pass --comfyui-base-url.",
        ),
        DoctorCheckPlan(
            name="gpu_status",
            commands=(
                (
                    *ssh_prefix,
                    "nvidia-smi",
                    "--query-gpu=memory.used,memory.total,utilization.gpu",
                    "--format=csv,noheader,nounits",
                ),
            ),
            planned_message="planned GPU status check",
            success_message="GPU status collected",
            failure_message="could not inspect GPU status",
            fix="Check whether NVIDIA drivers are available on the remote host.",
        ),
    )
    return RemoteWrapupPlan(host=host, remote_dir=remote_dir, checks=checks)


def run_remote_wrapup(
    options: RemoteWrapupOptions,
    *,
    runner: CommandRunner | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    plan = build_remote_wrapup_plan(options)
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
    else:
        command_runner = runner or SubprocessDoctorCommandRunner()
        records = [_run_check(check, command_runner) for check in plan.checks]
    return _report(plan, records, dry_run=dry_run)


def _report(plan: RemoteWrapupPlan, records: list[DoctorCheckRecord], *, dry_run: bool) -> dict[str, Any]:
    checks = [record.to_dict() for record in records]
    queue_idle = _queue_idle(checks)
    gpu_idle = _gpu_idle(checks)
    release_recommended = (not dry_run) and queue_idle is True and gpu_idle is True
    return {
        "ok": all(record.status != "failed" for record in records),
        "dry_run": dry_run,
        "host": plan.host,
        "remote_dir": plan.remote_dir,
        "checks": checks,
        "queue_idle": queue_idle,
        "gpu_idle": gpu_idle,
        "release_recommended": release_recommended,
        "release_message": (
            "Remote GPU appears idle; release or stop the rented instance to avoid further cost."
            if release_recommended
            else "Keep the instance only if more jobs are queued or debugging is still needed."
        ),
    }


def _queue_idle(checks: list[dict[str, Any]]) -> bool | None:
    check = _named(checks, "comfyui_queue")
    if not check or check.get("status") != "ok":
        return None
    text = str(check.get("stdout", ""))
    if '"queue_running": []' in text and '"queue_pending": []' in text:
        return True
    if '"queue_running":[]' in text and '"queue_pending":[]' in text:
        return True
    return False


def _gpu_idle(checks: list[dict[str, Any]]) -> bool | None:
    check = _named(checks, "gpu_status")
    if not check or check.get("status") != "ok":
        return None
    stdout = str(check.get("stdout", "")).strip()
    if not stdout:
        return None
    try:
        _used, _total, util = [int(part.strip()) for part in stdout.splitlines()[0].split(",")[:3]]
    except ValueError:
        return None
    return util <= 5


def _named(checks: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for check in checks:
        if check.get("name") == name:
            return check
    return None
