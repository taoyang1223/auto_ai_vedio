import json
import subprocess
import sys
from pathlib import Path

from auto_video.remote_transport import CommandResult
from auto_video.wan_remote_smoke import WanRemoteSmokeOptions, build_wan_remote_smoke_plan, execute_wan_remote_smoke

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "wan_remote_smoke.py"


def test_build_wan_remote_smoke_plan_includes_three_commands(tmp_path: Path):
    project = tmp_path / "demo"
    plan = build_wan_remote_smoke_plan(
        WanRemoteSmokeOptions(
            project=project,
            host="gpu-box",
            remote_dir="/data/auto-video/jobs/demo",
            wan_base_url="http://127.0.0.1:8082",
            require_i2v=True,
            ssh_options=("StrictHostKeyChecking=no",),
        )
    )

    assert plan["dry_run"] is True
    assert plan["commands"]["remote_doctor"] == [
        sys.executable,
        "-m",
        "auto_video",
        "remote",
        "doctor",
        "--host",
        "gpu-box",
        "--remote-dir",
        "/data/auto-video/jobs/demo",
        "--ssh-option",
        "StrictHostKeyChecking=no",
    ]
    assert plan["commands"]["wan_runtime_doctor"] == [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "gpu-box",
        "WAN_BASE_URL=http://127.0.0.1:8082",
        "python",
        "-m",
        "auto_video.wan_runtime_doctor",
        "--base-url-env",
        "WAN_BASE_URL",
        "--require-i2v",
    ]
    assert plan["commands"]["remote_run"] == [
        sys.executable,
        "-m",
        "auto_video",
        "remote",
        "run",
        project.as_posix(),
        "--provider",
        "wan_http",
        "--kind",
        "video",
        "--host",
        "gpu-box",
        "--remote-dir",
        "/data/auto-video/jobs/demo",
        "--ssh-option",
        "StrictHostKeyChecking=no",
        "--remote-env",
        "WAN_BASE_URL=http://127.0.0.1:8082",
    ]


class RecordingRunner:
    def __init__(self, *, fail_at: int | None = None):
        self.fail_at = fail_at
        self.commands: list[tuple[str, ...]] = []

    def run(self, command):
        command = tuple(command)
        self.commands.append(command)
        if self.fail_at and len(self.commands) == self.fail_at:
            return CommandResult(command=command, returncode=1, stderr="failed")
        return CommandResult(command=command, stdout="ok")


def test_execute_wan_remote_smoke_runs_commands_in_order(tmp_path: Path):
    options = WanRemoteSmokeOptions(
        project=tmp_path / "demo",
        host="gpu-box",
        remote_dir="/data/auto-video/jobs/demo",
        wan_base_url="http://127.0.0.1:8082",
    )
    runner = RecordingRunner()

    result = execute_wan_remote_smoke(options, runner=runner)

    assert result["ok"] is True
    assert [step["name"] for step in result["steps"]] == ["remote_doctor", "wan_runtime_doctor", "remote_run"]
    assert [command[0] for command in runner.commands] == [sys.executable, "ssh", sys.executable]


def test_wan_remote_smoke_keeps_script_doctor_targets_as_paths(tmp_path: Path):
    plan = build_wan_remote_smoke_plan(
        WanRemoteSmokeOptions(
            project=tmp_path / "demo",
            host="gpu-box",
            remote_dir="/data/auto-video/jobs/demo",
            wan_base_url="http://127.0.0.1:8082",
            remote_wan_doctor="/opt/auto-video/wan_runtime_doctor.py",
        )
    )

    assert plan["commands"]["wan_runtime_doctor"][3:5] == [
        "python",
        "/opt/auto-video/wan_runtime_doctor.py",
    ]


def test_execute_wan_remote_smoke_stops_on_failure(tmp_path: Path):
    options = WanRemoteSmokeOptions(
        project=tmp_path / "demo",
        host="gpu-box",
        remote_dir="/data/auto-video/jobs/demo",
        wan_base_url="http://127.0.0.1:8082",
    )
    runner = RecordingRunner(fail_at=2)

    result = execute_wan_remote_smoke(options, runner=runner)

    assert result["ok"] is False
    assert [step["status"] for step in result["steps"]] == ["ok", "failed"]
    assert len(runner.commands) == 2


def test_wan_remote_smoke_script_prints_dry_run_plan(tmp_path: Path):
    completed = subprocess.run(
        [
            sys.executable,
            SCRIPT.as_posix(),
            "--project",
            (tmp_path / "demo").as_posix(),
            "--host",
            "gpu-box",
            "--remote-dir",
            "/data/auto-video/jobs/demo",
            "--wan-base-url",
            "http://127.0.0.1:8082",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["dry_run"] is True
    assert payload["commands"]["remote_run"][-2:] == ["--remote-env", "WAN_BASE_URL=http://127.0.0.1:8082"]
