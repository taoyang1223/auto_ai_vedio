from pathlib import Path

import pytest

from auto_video.errors import ConfigError
from auto_video.project import load_project
from auto_video.remote_transport import RemoteRunOptions, build_remote_run_plan


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


def test_build_remote_run_plan_rejects_local_dir_inside_project(demo_project_files):
    project = load_project(demo_project_files)

    with pytest.raises(ConfigError) as exc:
        build_remote_run_plan(
            project,
            RemoteRunOptions(host="gpu-box", remote_dir="/data/demo", local_dir=demo_project_files / "remote-work"),
        )

    assert "project root" in str(exc.value)
