import json
import shutil
from pathlib import Path

from auto_video import remote_doctor
from auto_video import remote_transport
from auto_video.cli import main
from auto_video.remote_transport import CommandResult
from auto_video.worker_runner import run_worker_bundle


class CliFakeRemoteRunner:
    def __init__(self, remote_bundle: Path):
        self.remote_bundle = remote_bundle
        self.commands: list[tuple[str, ...]] = []

    def run(self, command):
        command = tuple(command)
        self.commands.append(command)
        if len(self.commands) == 1:
            shutil.copytree(Path(command[-2]), self.remote_bundle, dirs_exist_ok=True)
        elif len(self.commands) == 2:
            run_worker_bundle(self.remote_bundle)
        elif len(self.commands) == 3:
            shutil.copytree(self.remote_bundle, Path(command[-1]), dirs_exist_ok=True)
        return CommandResult(command=command)


class CliDoctorRunner:
    def __init__(self, *, fail_when: str | None = None):
        self.fail_when = fail_when
        self.commands: list[tuple[str, ...]] = []

    def run(self, command):
        command = tuple(command)
        self.commands.append(command)
        if self.fail_when and self.fail_when in command:
            return CommandResult(command=command, returncode=1, stderr=f"{self.fail_when} missing")
        return CommandResult(command=command, stdout="ok\n")


def test_remote_doctor_cli_dry_run_prints_planned_checks(monkeypatch, capsys):
    runner = CliDoctorRunner()
    monkeypatch.setattr(remote_doctor, "SubprocessDoctorCommandRunner", lambda: runner)

    assert (
        main(
            [
                "remote",
                "doctor",
                "--host",
                "gpu-box",
                "--remote-dir",
                "/data/auto-video/jobs/demo",
                "--dry-run",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert [check["status"] for check in payload["checks"]] == ["planned"] * 7
    assert runner.commands == []


def test_remote_doctor_cli_success_returns_zero(monkeypatch, capsys):
    runner = CliDoctorRunner()
    monkeypatch.setattr(remote_doctor, "SubprocessDoctorCommandRunner", lambda: runner)

    assert (
        main(
            [
                "remote",
                "doctor",
                "--host",
                "gpu-box",
                "--remote-dir",
                "/data/auto-video/jobs/demo",
                "--ssh-option",
                "StrictHostKeyChecking=no",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is True
    assert payload["checks"][2]["command"] == [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "gpu-box",
        "true",
    ]
    assert len(runner.commands) == 8


def test_remote_doctor_cli_failure_returns_one(monkeypatch, capsys):
    runner = CliDoctorRunner(fail_when="rsync")
    monkeypatch.setattr(remote_doctor, "SubprocessDoctorCommandRunner", lambda: runner)

    assert (
        main(
            [
                "remote",
                "doctor",
                "--host",
                "gpu-box",
                "--remote-dir",
                "/data/auto-video/jobs/demo",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is False
    assert [check["name"] for check in payload["checks"] if check["status"] == "failed"] == [
        "local_rsync",
        "remote_rsync",
    ]


def test_remote_cli_dry_run_prints_commands_without_manifest(tmp_path: Path, capsys):
    project = tmp_path / "demo"
    local_dir = tmp_path / "remote-work"
    assert main(["init", str(project)]) == 0

    assert (
        main(
            [
                "remote",
                "run",
                str(project),
                "--provider",
                "mock",
                "--kind",
                "video",
                "--host",
                "gpu-box",
                "--remote-dir",
                "/data/auto-video/jobs/demo",
                "--local-dir",
                str(local_dir),
                "--ssh-option",
                "StrictHostKeyChecking=no",
                "--remote-env",
                "WAN_BASE_URL=http://127.0.0.1:8082",
                "--dry-run",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["dry_run"] is True
    assert payload["host"] == "gpu-box"
    assert payload["remote_dir"] == "/data/auto-video/jobs/demo"
    assert payload["commands"]["run"] == [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "gpu-box",
        "WAN_BASE_URL=http://127.0.0.1:8082",
        "auto-video",
        "worker",
        "run",
        "/data/auto-video/jobs/demo",
    ]
    assert not (project / "manifest.json").exists()
    assert not (local_dir / "bundle").exists()


def test_remote_cli_lists_project_profiles(tmp_path: Path, capsys):
    project = tmp_path / "demo"
    assert main(["init", str(project)]) == 0
    with (project / "project.yaml").open("a", encoding="utf-8") as handle:
        handle.write(
            """
remote_profiles:
  autodl_5090:
    host: root@gpu-box
    remote_dir: /root/auto-video/jobs/demo
""",
        )

    assert main(["remote", "profiles", str(project)]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload == {"profiles": ["autodl_5090"]}


def test_remote_cli_dry_run_uses_project_profile(tmp_path: Path, capsys):
    project = tmp_path / "demo"
    local_dir = tmp_path / "profile-remote-work"
    assert main(["init", str(project)]) == 0
    with (project / "project.yaml").open("a", encoding="utf-8") as handle:
        handle.write(
            f"""
remote_profiles:
  autodl_5090:
    host: root@gpu-box
    remote_dir: /root/auto-video/jobs/demo
    local_dir: {local_dir.as_posix()}
    remote_auto_video: /opt/auto-ai-video/.venv/bin/auto-video
    ssh_options:
      - Port=13159
    remote_env:
      COMFYUI_BASE_URL: http://127.0.0.1:6006
      COMFYUI_WORKFLOW: /root/zealman-app/workflows/G10.json
""",
        )

    assert (
        main(
            [
                "remote",
                "run",
                str(project),
                "--profile",
                "autodl_5090",
                "--provider",
                "comfyui_wan",
                "--kind",
                "video",
                "--dry-run",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["dry_run"] is True
    assert payload["host"] == "root@gpu-box"
    assert payload["remote_dir"] == "/root/auto-video/jobs/demo"
    assert payload["local_bundle"] == (local_dir / "bundle").as_posix()
    assert payload["commands"]["upload"][:4] == ["rsync", "-az", "-e", "ssh -o Port=13159"]
    assert payload["commands"]["run"] == [
        "ssh",
        "-o",
        "Port=13159",
        "root@gpu-box",
        "COMFYUI_BASE_URL=http://127.0.0.1:6006",
        "COMFYUI_WORKFLOW=/root/zealman-app/workflows/G10.json",
        "/opt/auto-ai-video/.venv/bin/auto-video",
        "worker",
        "run",
        "/root/auto-video/jobs/demo",
    ]
    assert not (project / "manifest.json").exists()


def test_remote_cli_requires_host_without_profile(tmp_path: Path, capsys):
    project = tmp_path / "demo"
    assert main(["init", str(project)]) == 0

    assert (
        main(
            [
                "remote",
                "run",
                str(project),
                "--remote-dir",
                "/data/auto-video/jobs/demo",
                "--dry-run",
            ]
        )
        == 1
    )

    assert "--host is required" in capsys.readouterr().out


def test_remote_cli_fake_execution_imports_manifest(tmp_path: Path, monkeypatch, capsys):
    project = tmp_path / "demo"
    local_dir = tmp_path / "remote-work"
    remote_bundle = tmp_path / "fake-remote-bundle"
    fake_runner = CliFakeRemoteRunner(remote_bundle)
    monkeypatch.setattr(remote_transport, "SubprocessCommandRunner", lambda: fake_runner)
    assert main(["init", str(project)]) == 0

    assert (
        main(
            [
                "remote",
                "run",
                str(project),
                "--provider",
                "mock",
                "--kind",
                "video",
                "--host",
                "fake-gpu",
                "--remote-dir",
                "/tmp/remote-bundle",
                "--local-dir",
                str(local_dir),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert [command[0] for command in fake_runner.commands] == ["rsync", "ssh", "rsync"]
    assert payload["dry_run"] is False
    assert payload["imported"] == ["demo_ad:S01:video:mock"]
    assert payload["failed"] == []
    assert (project / "manifest.json").exists()
    assert (project / "generated" / "clips" / "S01.mp4").exists()


def test_checked_in_example_remote_dry_run(tmp_path: Path, capsys):
    local_dir = tmp_path / "example-remote-work"

    assert (
        main(
            [
                "remote",
                "run",
                "examples/demo_project",
                "--provider",
                "mock",
                "--kind",
                "video",
                "--host",
                "gpu-box",
                "--remote-dir",
                "/data/auto-video/jobs/demo",
                "--local-dir",
                str(local_dir),
                "--dry-run",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["dry_run"] is True
    assert payload["commands"]["upload"][0] == "rsync"
    assert payload["commands"]["run"][0] == "ssh"
    assert not (Path("examples/demo_project") / "manifest.json").exists()
