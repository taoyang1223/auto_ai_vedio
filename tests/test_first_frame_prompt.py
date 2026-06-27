import json

from auto_video.first_frame_prompt import (
    draft_first_frame_prompts,
    load_saved_first_frame_prompts,
    save_first_frame_prompts,
)
from auto_video.project import load_project


def test_drafts_first_frame_prompt_from_project_and_refs(demo_project_files):
    config_path = demo_project_files / "project.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + """
prompt_profile:
  subject: 同一位夜间创作者
  visual_style: premium cinematic commercial
  negative: watermark, bad hands
""",
        encoding="utf-8",
    )

    prompt = draft_first_frame_prompts(load_project(demo_project_files))[0]

    assert prompt["shot_id"] == "S01"
    assert prompt["has_first_frame"] is False
    assert "First-frame key visual for shot S01" in prompt["prompt"]
    assert "同一位夜间创作者" in prompt["prompt"]
    assert "A tired person at a cold desk" in prompt["prompt"]
    assert "首帧 / 保持主体" in prompt["prompt"]
    assert prompt["refs"][0]["role_label"] == "首帧"
    assert prompt["negative_prompt"].count("watermark") == 1
    assert "bad hands" in prompt["negative_prompt"]


def test_saves_first_frame_prompt_overrides(demo_project_files):
    project = load_project(demo_project_files)
    saved = save_first_frame_prompts(
        project,
        [
            {
                "shot_id": "S01",
                "prompt": "custom hero still frame",
                "negative_prompt": "text, watermark",
            }
        ],
    )

    payload = json.loads((demo_project_files / "assets" / "first_frame_prompts.json").read_text(encoding="utf-8"))
    loaded = load_saved_first_frame_prompts(demo_project_files)

    assert payload["prompts"][0]["shot_id"] == "S01"
    assert loaded["S01"]["prompt"] == "custom hero still frame"
    assert saved[0]["prompt"] == "custom hero still frame"
    assert saved[0]["saved"] is True
