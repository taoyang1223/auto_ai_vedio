from auto_video.pipeline import generate_images, generate_videos
from auto_video.project import load_project


def test_images_dry_run_does_not_write_manifest(demo_project_files):
    project = load_project(demo_project_files)
    plan = generate_images(project, provider_name="mock", dry_run=True)
    assert plan["dry_run"] is True
    assert plan["planned"][0]["shot_id"] == "S01"
    assert not (demo_project_files / "manifest.json").exists()


def test_mock_video_generation_writes_clip_and_manifest(demo_project_files):
    project = load_project(demo_project_files)
    results = generate_videos(project, provider_name="mock", dry_run=False)
    clip = demo_project_files / "generated" / "clips" / "S01.mp4"
    manifest = demo_project_files / "manifest.json"
    assert results[0].path == clip
    assert clip.read_text(encoding="utf-8").startswith("mock video")
    assert '"clip": "generated/clips/S01.mp4"' in manifest.read_text(encoding="utf-8")
