from auto_video.project import load_project
from auto_video.prompts import plan_prompt


def test_wan_prompt_prioritizes_motion_fields(demo_project_files):
    project = load_project(demo_project_files)
    prompt = plan_prompt(project.shots[0], provider="wan")
    assert "A tired person at a cold desk" in prompt
    assert "Camera: slow_dolly_in" in prompt
    assert "Environment motion: screen flicker" in prompt
    assert "Negative: text, watermark" in prompt


def test_seedance_prompt_includes_reference_usage(demo_project_files):
    project = load_project(demo_project_files)
    prompt = plan_prompt(project.shots[0], provider="seedance")
    assert "Shot S01" in prompt
    assert "Duration: 5.0s" in prompt
    assert "first_frame" in prompt
    assert "preserve_subject" in prompt
    assert "Audio intent: quiet room tone" in prompt


def test_prompt_profile_is_injected_into_wan_prompt(demo_project_files):
    with (demo_project_files / "project.yaml").open("a", encoding="utf-8") as handle:
        handle.write(
            """
prompt_profile:
  subject: same product creator
  character: consistent wardrobe and face
  setting: warm modern studio
  visual_style: premium commercial film
  negative: text, identity drift, style drift
""",
        )
    project = load_project(demo_project_files)

    prompt = plan_prompt(project.shots[0], provider="wan", profile=project.config.prompt_profile)

    assert "Subject: same product creator" in prompt
    assert "Character continuity: consistent wardrobe and face" in prompt
    assert "Visual style: premium commercial film" in prompt
    assert "Negative: text, watermark, identity drift, style drift" in prompt
