from pathlib import Path

import pytest

from auto_video.errors import ConfigError
from auto_video.project import load_project
from auto_video.workflow_registry import (
    comfyui_wan_adapter_options,
    list_workflows,
    show_workflow,
    workflow_env_exports,
)


def _append_workflow(project: Path) -> None:
    with (project / "project.yaml").open("a", encoding="utf-8") as handle:
        handle.write(
            """
comfyui_workflows:
  wan2_2_smoothmix_i2v:
    title: Wan2.2 SmoothMix I2V
    provider: comfyui_wan
    kind: image_to_video
    base_url: http://127.0.0.1:6006
    base_url_env: COMFYUI_BASE_URL
    workflow_env: COMFYUI_WORKFLOW
    workflow_path: /root/zealman-app/workflows/G10.json
    profile_env: COMFYUI_WORKFLOW_PROFILE
    tags:
      - wan2.2
      - autodl
    parameters:
      seed: 123
      steps: 12
      guidance_scale: 1.5
    nodes:
      prompt:
        id: "900"
        input: prompt_text
      negative:
        id: "901"
        input: negative_text
      image:
        id: "902"
        input: first_frame
      video:
        id: "903"
        frame_rate_input: fps
        filename_prefix_input: prefix
      steps:
        ids:
          - "904"
          - "905"
        steps_input: sample_steps
        cfg_input: cfg_scale
""",
        )


def test_workflow_registry_lists_and_shows_profiles(demo_project_files):
    _append_workflow(demo_project_files)
    project = load_project(demo_project_files)

    workflows = list_workflows(project)
    profile = show_workflow(project, "wan2_2_smoothmix_i2v")

    assert workflows == [
        {
            "name": "wan2_2_smoothmix_i2v",
            "title": "Wan2.2 SmoothMix I2V",
            "provider": "comfyui_wan",
            "kind": "image_to_video",
            "workflow_path": "/root/zealman-app/workflows/G10.json",
            "base_url_env": "COMFYUI_BASE_URL",
            "workflow_env": "COMFYUI_WORKFLOW",
            "profile_env": "COMFYUI_WORKFLOW_PROFILE",
            "tags": ["wan2.2", "autodl"],
        }
    ]
    assert profile["title"] == "Wan2.2 SmoothMix I2V"


def test_workflow_registry_builds_env_exports(demo_project_files):
    _append_workflow(demo_project_files)
    project = load_project(demo_project_files)

    assert workflow_env_exports(project, "wan2_2_smoothmix_i2v") == [
        "COMFYUI_BASE_URL=http://127.0.0.1:6006",
        "COMFYUI_WORKFLOW=/root/zealman-app/workflows/G10.json",
        "COMFYUI_WORKFLOW_PROFILE=wan2_2_smoothmix_i2v",
    ]


def test_workflow_registry_builds_adapter_options(demo_project_files):
    _append_workflow(demo_project_files)
    project = load_project(demo_project_files)

    options = comfyui_wan_adapter_options(project, "wan2_2_smoothmix_i2v")

    assert options["workflow"] == "/root/zealman-app/workflows/G10.json"
    assert options["seed"] == 123
    assert options["steps"] == 12
    assert options["guidance_scale"] == 1.5
    assert options["prompt_node"] == "900"
    assert options["prompt_input"] == "prompt_text"
    assert options["video_node"] == "903"
    assert options["frame_rate_input"] == "fps"
    assert options["steps_node"] == ["904", "905"]
    assert options["steps_input"] == "sample_steps"


def test_unknown_workflow_profile_is_config_error(demo_project_files):
    project = load_project(demo_project_files)

    with pytest.raises(ConfigError) as exc:
        show_workflow(project, "missing")

    assert "unknown ComfyUI workflow profile" in str(exc.value)
