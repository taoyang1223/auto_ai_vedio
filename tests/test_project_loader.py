from pathlib import Path

import pytest

from auto_video.errors import AssetError, ConfigError
from auto_video.project import load_project, resolve_project_path


def test_load_project_reads_config_and_shots(demo_project_files):
    project = load_project(demo_project_files)
    assert project.config.name == "demo_ad"
    assert project.config.width == 1080
    assert project.shots[0].id == "S01"
    assert project.shots[0].refs[0].path == "assets/refs/S01.txt"


def test_load_project_reads_remote_profiles(demo_project_files):
    with (demo_project_files / "project.yaml").open("a", encoding="utf-8") as handle:
        handle.write(
            """
remote_profiles:
  autodl_5090:
    host: root@gpu-box
    remote_dir: /root/auto-video/jobs/demo
    remote_auto_video: /opt/auto-ai-video/.venv/bin/auto-video
    ssh_options:
      - Port=13159
    remote_env:
      COMFYUI_BASE_URL: http://127.0.0.1:6006
""",
        )

    project = load_project(demo_project_files)

    profile = project.config.remote_profiles["autodl_5090"]
    assert profile["host"] == "root@gpu-box"
    assert profile["ssh_options"] == ["Port=13159"]
    assert profile["remote_env"]["COMFYUI_BASE_URL"] == "http://127.0.0.1:6006"


def test_resolve_project_path_rejects_escape(demo_project_files):
    with pytest.raises(AssetError) as exc:
        resolve_project_path(demo_project_files, "../secret.txt")
    assert "escapes project root" in str(exc.value)


def test_missing_shots_file_is_config_error(tmp_path: Path):
    project = tmp_path / "bad"
    project.mkdir()
    (project / "project.yaml").write_text("name: bad\n", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_project(project)
    assert "shots.json" in str(exc.value)
