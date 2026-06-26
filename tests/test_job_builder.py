from auto_video.job_builder import build_jobs
from auto_video.project import load_project


def test_build_video_job_preserves_seedance_style_controls(demo_project_files):
    project = load_project(demo_project_files)

    jobs = build_jobs(project, kind="video", provider_name="mock")

    assert len(jobs) == 1
    job = jobs[0]
    assert job.id == "demo_ad:S01:video:mock"
    assert job.output_path == "generated/clips/S01.mp4"
    assert job.duration == 5.0
    assert job.refs[0].path == "assets/refs/S01.txt"
    assert job.refs[0].exists is True
    assert job.controls.camera_motion == "slow_dolly_in"
    assert job.controls.environment_motion == "screen flicker"
    assert job.controls.audio_intent == "quiet room tone"
    assert "A tired person at a cold desk" in job.prompt


def test_build_jobs_uses_only_filter(demo_project_files):
    project = load_project(demo_project_files)

    jobs = build_jobs(project, kind="video", provider_name="mock", only={"S99"})

    assert jobs == []


def test_project_loader_reads_provider_config(demo_project_files):
    (demo_project_files / "project.yaml").write_text(
        """
name: demo_ad
aspect_ratio: "9:16"
width: 1080
height: 1920
fps: 30
default_video_provider: mock
default_image_provider: mock
default_audio_provider: mock
providers:
  mock:
    mode: local
    timeout_seconds: 45
    max_attempts: 3
render:
  transition:
    type: fade
    duration: 0.6
  bgm_volume: 0.2
""".strip(),
        encoding="utf-8",
    )

    project = load_project(demo_project_files)

    assert project.config.providers["mock"].mode == "local"
    assert project.config.providers["mock"].timeout_seconds == 45
    assert project.config.providers["mock"].max_attempts == 3
