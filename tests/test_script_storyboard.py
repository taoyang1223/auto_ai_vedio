import pytest

from auto_video.errors import ConfigError
from auto_video.project import load_project
from auto_video.script_storyboard import draft_storyboard_from_script


def test_script_storyboard_drafts_requested_shot_count(demo_project_files):
    project = load_project(demo_project_files)

    result = draft_storyboard_from_script(
        project,
        {
            "script": "一位创作者准备发布视频。桌面上的故事板开始发光。最终成片在大屏幕上播放。",
            "shot_count": 4,
            "duration": 3.5,
            "provider": "comfyui_wan",
        },
    )

    assert result["meta"]["shot_count"] == 4
    assert len(result["shots"]) == 4
    assert result["shots"][0]["id"] == "S01"
    assert result["shots"][0]["provider"] == "comfyui_wan"
    assert result["shots"][0]["duration"] == 3.5
    assert "一位创作者准备发布视频" in result["shots"][0]["visual_prompt"]
    assert result["shots"][-1]["title"].startswith("结果揭示")


def test_script_storyboard_uses_project_prompt_profile(demo_project_files):
    with (demo_project_files / "project.yaml").open("a", encoding="utf-8") as handle:
        handle.write(
            """
prompt_profile:
  subject: 同一位 AI 视频创作者
  setting: 现代影像工作室
  visual_style: premium cinematic demo
  camera_style: smooth controlled camera
""",
        )
    project = load_project(demo_project_files)

    result = draft_storyboard_from_script(project, {"script": "创作者把想法变成视频", "shot_count": 2})

    assert "同一位 AI 视频创作者" in result["shots"][0]["visual_prompt"]
    assert "现代影像工作室" in result["shots"][0]["visual_prompt"]
    assert "smooth controlled camera" in result["shots"][0]["camera_motion"]


def test_script_storyboard_rejects_empty_script(demo_project_files):
    project = load_project(demo_project_files)

    with pytest.raises(ConfigError) as exc:
        draft_storyboard_from_script(project, {"script": "   "})

    assert "脚本不能为空" in str(exc.value)
