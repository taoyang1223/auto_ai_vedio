from pathlib import Path

import pytest

from auto_video.errors import ConfigError
from auto_video.project import load_project
from auto_video.remote_profiles import build_remote_run_options_from_profile, list_remote_profiles


def _append_profile(project: Path) -> None:
    with (project / "project.yaml").open("a", encoding="utf-8") as handle:
        handle.write(
            """
remote_profiles:
  autodl_5090:
    host: root@gpu-box
    remote_dir: /root/auto-video/jobs/demo
    local_dir: /tmp/auto-video-demo
    remote_auto_video: /opt/auto-ai-video/.venv/bin/auto-video
    ssh_options:
      - Port=13159
    rsync_options:
      - --info=progress2
    remote_env:
      COMFYUI_BASE_URL: http://127.0.0.1:6006
      COMFYUI_WORKFLOW: /root/zealman-app/workflows/G10.json
""",
        )


def test_build_remote_run_options_from_profile_merges_cli_overrides(demo_project_files, tmp_path):
    _append_profile(demo_project_files)
    project = load_project(demo_project_files)

    options = build_remote_run_options_from_profile(
        project,
        profile_name="autodl_5090",
        host=None,
        remote_dir=None,
        provider_name="comfyui_wan",
        kind="video",
        only={"S01"},
        failed_only=False,
        skip_succeeded=True,
        local_dir=tmp_path / "local-override",
        remote_auto_video=None,
        ssh_options=("StrictHostKeyChecking=no",),
        rsync_options=(),
        remote_env=("COMFYUI_BASE_URL=http://127.0.0.1:7000",),
    )

    assert options.host == "root@gpu-box"
    assert options.remote_dir == "/root/auto-video/jobs/demo"
    assert options.local_dir == tmp_path / "local-override"
    assert options.remote_auto_video == "/opt/auto-ai-video/.venv/bin/auto-video"
    assert options.provider_name == "comfyui_wan"
    assert options.only == {"S01"}
    assert options.failed_only is False
    assert options.skip_succeeded is True
    assert options.ssh_options == ("Port=13159", "StrictHostKeyChecking=no")
    assert options.rsync_options == ("--info=progress2",)
    assert options.remote_env == (
        "COMFYUI_BASE_URL=http://127.0.0.1:7000",
        "COMFYUI_WORKFLOW=/root/zealman-app/workflows/G10.json",
    )


def test_list_remote_profiles_returns_sorted_names(demo_project_files):
    _append_profile(demo_project_files)
    project = load_project(demo_project_files)

    assert list_remote_profiles(project) == ["autodl_5090"]


def test_unknown_remote_profile_is_config_error(demo_project_files):
    project = load_project(demo_project_files)

    with pytest.raises(ConfigError) as exc:
        build_remote_run_options_from_profile(
            project,
            profile_name="missing",
            host=None,
            remote_dir=None,
            provider_name=None,
            kind="video",
            only=None,
            failed_only=False,
            skip_succeeded=False,
            local_dir=None,
            remote_auto_video=None,
            ssh_options=(),
            rsync_options=(),
            remote_env=(),
        )

    assert "remote profile 'missing'" in str(exc.value)
