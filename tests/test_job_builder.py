import json

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


def test_build_lipsync_job_includes_source_video_and_audio_refs(demo_project_files):
    clip = demo_project_files / "generated" / "clips" / "S01.mp4"
    audio = demo_project_files / "generated" / "audio" / "S01.wav"
    clip.parent.mkdir(parents=True, exist_ok=True)
    audio.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"clip")
    audio.write_bytes(b"audio")
    (demo_project_files / "manifest.json").write_text(
        json.dumps(
            {
                "project": "demo_ad",
                "schema_version": "0.1",
                "assets": {},
                "shots": {
                    "S01": {
                        "status": "generated",
                        "clip": "generated/clips/S01.mp4",
                        "audio": "generated/audio/S01.wav",
                    }
                },
                "renders": {},
                "jobs": {},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    project = load_project(demo_project_files)

    job = build_jobs(project, kind="lipsync", provider_name="mock")[0]
    refs = {(ref.type, ref.role): ref for ref in job.refs}

    assert job.id == "demo_ad:S01:lipsync:mock"
    assert job.output_path == "generated/lipsync/S01.mp4"
    assert refs[("video", "source_video")].path == "generated/clips/S01.mp4"
    assert refs[("audio", "source_audio")].path == "generated/audio/S01.wav"
    assert refs[("video", "source_video")].exists is True
    assert "Late night again" in job.prompt


def test_build_lipsync_job_ignores_first_frame_refs(demo_project_files):
    clip = demo_project_files / "generated" / "clips" / "S01.mp4"
    audio = demo_project_files / "generated" / "audio" / "S01.wav"
    clip.parent.mkdir(parents=True, exist_ok=True)
    audio.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"clip")
    audio.write_bytes(b"audio")
    (demo_project_files / "manifest.json").write_text(
        json.dumps(
            {
                "project": "demo_ad",
                "schema_version": "0.1",
                "assets": {},
                "shots": {
                    "S01": {
                        "status": "generated",
                        "clip": "generated/clips/S01.mp4",
                        "audio": "generated/audio/S01.wav",
                    }
                },
                "renders": {},
                "jobs": {},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    project = load_project(demo_project_files)

    job = build_jobs(project, kind="lipsync", provider_name="mock")[0]

    assert [(ref.type, ref.role) for ref in job.refs] == [
        ("video", "source_video"),
        ("audio", "source_audio"),
    ]


def test_build_lipsync_jobs_skip_narrator_shots(demo_project_files):
    (demo_project_files / "shots.json").write_text(
        json.dumps(
            {
                "shots": [
                    {
                        "id": "S01",
                        "title": "旁白空镜",
                        "duration": 5,
                        "speaker": "narrator",
                        "visual_prompt": "quiet room",
                        "subtitle": "旁白介绍房间。",
                    },
                    {
                        "id": "S02",
                        "title": "角色对白",
                        "duration": 4,
                        "speaker": "char_hero",
                        "visual_prompt": "hero speaking",
                        "subtitle": "我醒了。",
                    },
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    project = load_project(demo_project_files)

    jobs = build_jobs(project, kind="lipsync", provider_name="mock")

    assert [job.shot_id for job in jobs] == ["S02"]


def test_build_jobs_injects_project_prompt_profile(demo_project_files):
    with (demo_project_files / "project.yaml").open("a", encoding="utf-8") as handle:
        handle.write(
            """
prompt_profile:
  subject: same cinematic creator
  continuity: keep the same studio layout
  negative: identity drift
""",
        )
    project = load_project(demo_project_files)

    jobs = build_jobs(project, kind="video", provider_name="wan")

    assert "Subject: same cinematic creator" in jobs[0].prompt
    assert "Continuity rules: keep the same studio layout" in jobs[0].prompt
    assert "Negative: text, watermark, identity drift" in jobs[0].prompt


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
