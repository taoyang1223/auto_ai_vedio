import json

from auto_video.pipeline import generate_images, generate_videos, plan_jobs, submit_jobs
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


def test_mock_audio_generation_writes_wav_and_manifest(demo_project_files):
    project = load_project(demo_project_files)
    results = submit_jobs(project, kind="audio", provider_name="mock")
    audio = demo_project_files / "generated" / "audio" / "S01.wav"
    manifest = json.loads((demo_project_files / "manifest.json").read_text(encoding="utf-8"))

    assert results[0].path == audio
    assert audio.read_bytes().startswith(b"RIFF")
    assert manifest["shots"]["S01"]["audio"] == "generated/audio/S01.wav"
    assert manifest["jobs"]["demo_ad:S01:audio:mock"]["metadata"]["input_hash"]


def test_audio_plan_reruns_when_subtitle_changes(demo_project_files):
    project = load_project(demo_project_files)
    submit_jobs(project, kind="audio", provider_name="mock")
    shots_path = demo_project_files / "shots.json"
    payload = json.loads(shots_path.read_text(encoding="utf-8"))
    payload["shots"][0]["subtitle"] = "A new narration line"
    shots_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    project = load_project(demo_project_files)
    plan = plan_jobs(project, kind="audio", provider_name="mock", skip_succeeded=True)

    assert [job["shot_id"] for job in plan["planned"]] == ["S01"]
