from auto_video.pipeline import generate_videos
from auto_video.project import load_project
from auto_video.probe import probe_project
from auto_video.render import build_render_plan


def test_render_plan_uses_manifest_clip(demo_project_files):
    project = load_project(demo_project_files)
    generate_videos(project, provider_name="mock", dry_run=False)
    project = load_project(demo_project_files)

    plan = build_render_plan(project)
    assert plan["output"] == "renders/final.mp4"
    assert plan["shots"][0]["id"] == "S01"
    assert plan["shots"][0]["clip"] == "generated/clips/S01.mp4"
    assert plan["ffmpeg"][0] == "ffmpeg"


def test_probe_reports_missing_or_mock_duration(demo_project_files):
    project = load_project(demo_project_files)
    generate_videos(project, provider_name="mock", dry_run=False)
    project = load_project(demo_project_files)

    report = probe_project(project, dry_run=True)
    assert report["dry_run"] is True
    assert report["shots"][0]["id"] == "S01"
    assert report["shots"][0]["manifest_duration"] == 5.0
