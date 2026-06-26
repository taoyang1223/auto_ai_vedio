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
