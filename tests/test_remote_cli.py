import json
import shutil
from pathlib import Path

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
        "auto-video",
        "worker",
        "run",
        "/data/auto-video/jobs/demo",
    ]
    assert not (project / "manifest.json").exists()
    assert not (local_dir / "bundle").exists()


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
