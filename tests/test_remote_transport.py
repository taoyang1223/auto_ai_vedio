from pathlib import Path
import shutil

import pytest

from auto_video.errors import ConfigError, ProviderError
from auto_video.project import load_project
from auto_video.remote_transport import CommandResult, RemoteRunOptions, build_remote_run_plan, run_remote_worker
from auto_video.worker_runner import run_worker_bundle


def test_build_remote_run_plan_includes_upload_run_and_download_commands(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    local_dir = tmp_path / "remote-work"

    plan = build_remote_run_plan(
        project,
        RemoteRunOptions(
            host="gpu-box",
            remote_dir="/data/auto-video/jobs/demo",
            local_dir=local_dir,
            remote_auto_video="/opt/auto-video",
            ssh_options=("StrictHostKeyChecking=no",),
            rsync_options=("--info=progress2",),
        ),
    )

    assert plan.project_root == demo_project_files.resolve()
    assert plan.local_dir == local_dir
    assert plan.local_bundle == local_dir / "bundle"
    assert plan.host == "gpu-box"
    assert plan.remote_dir == "/data/auto-video/jobs/demo"
    assert list(plan.upload) == [
        "rsync",
        "-az",
        "--info=progress2",
        "--delete",
        f"{(local_dir / 'bundle').as_posix()}/",
        "gpu-box:/data/auto-video/jobs/demo/",
    ]
    assert list(plan.run) == [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "gpu-box",
        "/opt/auto-video",
        "worker",
        "run",
        "/data/auto-video/jobs/demo",
    ]
    assert list(plan.download) == [
        "rsync",
        "-az",
        "--info=progress2",
        "--delete",
        "gpu-box:/data/auto-video/jobs/demo/",
        f"{(local_dir / 'bundle').as_posix()}/",
    ]


def test_build_remote_run_plan_uses_safe_default_local_dir(demo_project_files):
    project = load_project(demo_project_files)

    plan = build_remote_run_plan(
        project,
        RemoteRunOptions(host="gpu-box", remote_dir="/data/auto-video/jobs/demo"),
    )

    assert plan.local_bundle.name == "bundle"
    assert "auto-video-remote" in plan.local_bundle.as_posix()
    assert demo_project_files.resolve() not in plan.local_bundle.resolve().parents


def test_build_remote_run_plan_rejects_unsafe_host(demo_project_files, tmp_path):
    project = load_project(demo_project_files)

    with pytest.raises(ConfigError) as exc:
        build_remote_run_plan(
            project,
            RemoteRunOptions(host="bad host", remote_dir="/data/demo", local_dir=tmp_path / "work"),
        )

    assert "host" in str(exc.value)


def test_build_remote_run_plan_rejects_unsafe_remote_dir(demo_project_files, tmp_path):
    project = load_project(demo_project_files)

    with pytest.raises(ConfigError) as exc:
        build_remote_run_plan(
            project,
            RemoteRunOptions(host="gpu-box", remote_dir="relative/demo", local_dir=tmp_path / "work"),
        )

    assert "remote-dir" in str(exc.value)

    with pytest.raises(ConfigError) as control_exc:
        build_remote_run_plan(
            project,
            RemoteRunOptions(host="gpu-box", remote_dir="/data/demo;rm", local_dir=tmp_path / "work"),
        )

    assert "remote-dir" in str(control_exc.value)

    with pytest.raises(ConfigError) as root_exc:
        build_remote_run_plan(
            project,
            RemoteRunOptions(host="gpu-box", remote_dir="/", local_dir=tmp_path / "work"),
        )

    assert "remote-dir" in str(root_exc.value)

    with pytest.raises(ConfigError) as parent_exc:
        build_remote_run_plan(
            project,
            RemoteRunOptions(host="gpu-box", remote_dir="/data/../demo", local_dir=tmp_path / "work"),
        )

    assert "remote-dir" in str(parent_exc.value)


def test_build_remote_run_plan_rejects_local_dir_inside_project(demo_project_files):
    project = load_project(demo_project_files)

    with pytest.raises(ConfigError) as exc:
        build_remote_run_plan(
            project,
            RemoteRunOptions(host="gpu-box", remote_dir="/data/demo", local_dir=demo_project_files / "remote-work"),
        )

    assert "project root" in str(exc.value)


class FakeRemoteRunner:
    def __init__(self, remote_bundle: Path):
        self.remote_bundle = remote_bundle
        self.commands: list[tuple[str, ...]] = []

    def run(self, command):
        command = tuple(command)
        self.commands.append(command)
        if len(self.commands) == 1:
            source = Path(command[-2])
            shutil.copytree(source, self.remote_bundle, dirs_exist_ok=True)
        elif len(self.commands) == 2:
            run_worker_bundle(self.remote_bundle)
        elif len(self.commands) == 3:
            destination = Path(command[-1])
            shutil.copytree(self.remote_bundle, destination, dirs_exist_ok=True)
        return CommandResult(command=command)


class FailingUploadRunner:
    def __init__(self):
        self.commands: list[tuple[str, ...]] = []

    def run(self, command):
        self.commands.append(tuple(command))
        raise ProviderError("upload failed")


def test_run_remote_worker_exports_runs_downloads_and_imports(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    remote_bundle = tmp_path / "fake-remote-bundle"
    runner = FakeRemoteRunner(remote_bundle)

    summary = run_remote_worker(
        project,
        RemoteRunOptions(
            host="fake-gpu",
            remote_dir="/tmp/remote-bundle",
            local_dir=tmp_path / "local-run",
            provider_name="mock",
            kind="video",
        ),
        runner=runner,
    )

    assert [command[0] for command in runner.commands] == ["rsync", "ssh", "rsync"]
    assert summary["dry_run"] is False
    assert summary["project"] == "demo_ad"
    assert summary["imported"] == ["demo_ad:S01:video:mock"]
    assert summary["failed"] == []
    assert (demo_project_files / "manifest.json").exists()
    assert (demo_project_files / "generated" / "clips" / "S01.mp4").exists()
    assert (remote_bundle / "result.json").exists()


def test_run_remote_worker_dry_run_does_not_export_or_import(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    runner = FakeRemoteRunner(tmp_path / "remote")

    summary = run_remote_worker(
        project,
        RemoteRunOptions(
            host="fake-gpu",
            remote_dir="/tmp/remote-bundle",
            local_dir=tmp_path / "local-run",
            provider_name="mock",
            kind="video",
        ),
        runner=runner,
        dry_run=True,
    )

    assert summary["dry_run"] is True
    assert runner.commands == []
    assert not (tmp_path / "local-run" / "bundle").exists()
    assert not (demo_project_files / "manifest.json").exists()


def test_run_remote_worker_failed_upload_does_not_import(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    runner = FailingUploadRunner()

    with pytest.raises(ProviderError):
        run_remote_worker(
            project,
            RemoteRunOptions(
                host="fake-gpu",
                remote_dir="/tmp/remote-bundle",
                local_dir=tmp_path / "local-run",
                provider_name="mock",
                kind="video",
            ),
            runner=runner,
        )

    assert len(runner.commands) == 1
    assert not (demo_project_files / "manifest.json").exists()
