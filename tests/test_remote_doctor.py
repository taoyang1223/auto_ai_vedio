import pytest

from auto_video.errors import ConfigError
from auto_video.remote_doctor import (
    RemoteDoctorOptions,
    build_remote_doctor_plan,
    run_remote_doctor,
)
from auto_video.remote_transport import CommandResult


def test_build_remote_doctor_plan_includes_all_checks():
    plan = build_remote_doctor_plan(
        RemoteDoctorOptions(
            host="gpu-box",
            remote_dir="/data/auto-video/jobs/demo",
            remote_auto_video="/opt/auto-video",
            ssh_options=("StrictHostKeyChecking=no",),
        )
    )

    assert plan.host == "gpu-box"
    assert plan.remote_dir == "/data/auto-video/jobs/demo"
    assert [check.name for check in plan.checks] == [
        "local_ssh",
        "local_rsync",
        "ssh_connectivity",
        "remote_rsync",
        "remote_auto_video",
        "remote_worker_cli",
        "remote_dir_writable",
    ]
    assert plan.checks[0].commands == (("ssh", "-V"),)
    assert plan.checks[1].commands == (("rsync", "--version"),)
    assert plan.checks[2].commands == (
        ("ssh", "-o", "StrictHostKeyChecking=no", "gpu-box", "true"),
    )
    assert plan.checks[3].commands == (
        ("ssh", "-o", "StrictHostKeyChecking=no", "gpu-box", "command", "-v", "rsync"),
    )
    assert plan.checks[4].commands == (
        ("ssh", "-o", "StrictHostKeyChecking=no", "gpu-box", "/opt/auto-video", "--help"),
    )
    assert plan.checks[5].commands == (
        ("ssh", "-o", "StrictHostKeyChecking=no", "gpu-box", "/opt/auto-video", "worker", "run", "--help"),
    )
    assert plan.checks[6].commands == (
        ("ssh", "-o", "StrictHostKeyChecking=no", "gpu-box", "mkdir", "-p", "/data/auto-video/jobs/demo"),
        ("ssh", "-o", "StrictHostKeyChecking=no", "gpu-box", "test", "-w", "/data/auto-video/jobs/demo"),
    )


def test_build_remote_doctor_plan_rejects_unsafe_inputs():
    with pytest.raises(ConfigError) as host_exc:
        build_remote_doctor_plan(RemoteDoctorOptions(host="bad host", remote_dir="/data/demo"))
    assert "host" in str(host_exc.value)

    with pytest.raises(ConfigError) as dir_exc:
        build_remote_doctor_plan(RemoteDoctorOptions(host="gpu-box", remote_dir="/data/../demo"))
    assert "remote-dir" in str(dir_exc.value)

    with pytest.raises(ConfigError) as command_exc:
        build_remote_doctor_plan(
            RemoteDoctorOptions(host="gpu-box", remote_dir="/data/demo", remote_auto_video="auto video")
        )
    assert "remote-auto-video" in str(command_exc.value)

    with pytest.raises(ConfigError) as option_exc:
        build_remote_doctor_plan(
            RemoteDoctorOptions(host="gpu-box", remote_dir="/data/demo", ssh_options=("Port=22;rm",))
        )
    assert "ssh-option" in str(option_exc.value)


class RecordingDoctorRunner:
    def __init__(self, *, fail_when: str | None = None):
        self.fail_when = fail_when
        self.commands: list[tuple[str, ...]] = []

    def run(self, command):
        command = tuple(command)
        self.commands.append(command)
        if self.fail_when and self.fail_when in command:
            return CommandResult(command=command, returncode=1, stderr=f"{self.fail_when} missing")
        return CommandResult(command=command, stdout="ok\n")


def test_run_remote_doctor_dry_run_plans_without_running_commands():
    runner = RecordingDoctorRunner()

    report = run_remote_doctor(
        RemoteDoctorOptions(host="gpu-box", remote_dir="/data/auto-video/jobs/demo"),
        runner=runner,
        dry_run=True,
    )

    assert report["ok"] is True
    assert report["dry_run"] is True
    assert runner.commands == []
    assert [check["status"] for check in report["checks"]] == ["planned"] * 7
    assert report["checks"][6]["command"] == [
        ["ssh", "gpu-box", "mkdir", "-p", "/data/auto-video/jobs/demo"],
        ["ssh", "gpu-box", "test", "-w", "/data/auto-video/jobs/demo"],
    ]


def test_run_remote_doctor_success_report_contains_all_checks():
    runner = RecordingDoctorRunner()

    report = run_remote_doctor(
        RemoteDoctorOptions(host="gpu-box", remote_dir="/data/auto-video/jobs/demo"),
        runner=runner,
    )

    assert report["ok"] is True
    assert report["dry_run"] is False
    assert [check["status"] for check in report["checks"]] == ["ok"] * 7
    assert len(runner.commands) == 8


def test_run_remote_doctor_failure_report_keeps_checking():
    runner = RecordingDoctorRunner(fail_when="rsync")

    report = run_remote_doctor(
        RemoteDoctorOptions(host="gpu-box", remote_dir="/data/auto-video/jobs/demo"),
        runner=runner,
    )

    assert report["ok"] is False
    assert [check["name"] for check in report["checks"]] == [
        "local_ssh",
        "local_rsync",
        "ssh_connectivity",
        "remote_rsync",
        "remote_auto_video",
        "remote_worker_cli",
        "remote_dir_writable",
    ]
    failed = [check for check in report["checks"] if check["status"] == "failed"]
    assert [check["name"] for check in failed] == ["local_rsync", "remote_rsync"]
    assert all("fix" in check for check in failed)
    assert len(runner.commands) == 8
