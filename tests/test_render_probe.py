import json

import pytest

from auto_video.errors import RenderError
from auto_video.pipeline import generate_videos
from auto_video.project import load_project
from auto_video.probe import probe_project
from auto_video.render import assemble_project, build_render_plan


class FakeRenderRunner:
    def __init__(self):
        self.commands = []

    def run(self, command):
        self.commands.append(tuple(command))
        output = command[-1]
        with open(output, "wb") as handle:
            handle.write(b"final-video")


class FakeMediaProbeRunner:
    def __init__(self, payload, blackdetect_stderr=""):
        self.payload = payload
        self.blackdetect_stderr = blackdetect_stderr
        self.probed = []
        self.blackdetected = []

    def probe(self, path):
        self.probed.append(path)
        return self.payload

    def blackdetect(self, path):
        self.blackdetected.append(path)
        return self.blackdetect_stderr


def _ffprobe_payload(*, width=1080, height=1920, duration=5.0, fps="30/1"):
    return {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": width,
                "height": height,
                "duration": str(duration),
                "avg_frame_rate": fps,
                "pix_fmt": "yuv420p",
            }
        ],
        "format": {"duration": str(duration), "bit_rate": "1000000"},
    }


def test_render_plan_uses_manifest_clip(demo_project_files):
    project = load_project(demo_project_files)
    generate_videos(project, provider_name="mock", dry_run=False)
    project = load_project(demo_project_files)

    plan = build_render_plan(project)
    assert plan["output"] == "renders/final.mp4"
    assert plan["concat_file"] == "renders/final.concat.txt"
    assert plan["shots"][0]["id"] == "S01"
    assert plan["shots"][0]["clip"] == "generated/clips/S01.mp4"
    assert plan["shots"][0]["exists"] is True
    assert plan["shots"][0]["bytes"] > 0
    assert plan["ffmpeg"][0] == "ffmpeg"
    assert plan["ffmpeg"][-1].endswith("renders/final.mp4")


def test_assemble_project_runs_ffmpeg_and_records_render(demo_project_files):
    project = load_project(demo_project_files)
    generate_videos(project, provider_name="mock", dry_run=False)
    project = load_project(demo_project_files)
    runner = FakeRenderRunner()

    result = assemble_project(project, runner=runner)

    project = load_project(demo_project_files)
    assert result["status"] == "succeeded"
    assert runner.commands[0][0] == "ffmpeg"
    assert (demo_project_files / "renders" / "final.mp4").read_bytes() == b"final-video"
    assert (demo_project_files / "renders" / "final.concat.txt").read_text(encoding="utf-8").startswith("file '")
    subtitle = (demo_project_files / "renders" / "final.srt").read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:05,000" in subtitle
    assert "Late night again" in subtitle
    assert project.manifest["renders"]["final"]["path"] == "renders/final.mp4"
    assert project.manifest["renders"]["final"]["subtitle"] == "renders/final.srt"
    assert project.manifest["renders"]["final"]["subtitle_entries"] == 1


def test_assemble_project_archives_previous_final_render(demo_project_files):
    project = load_project(demo_project_files)
    generate_videos(project, provider_name="mock", dry_run=False)
    previous = demo_project_files / "renders" / "final.mp4"
    previous.parent.mkdir(parents=True, exist_ok=True)
    previous.write_bytes(b"old-final")
    project = load_project(demo_project_files)

    result = assemble_project(project, runner=FakeRenderRunner())

    project = load_project(demo_project_files)
    versions = project.manifest["renders"]["final"]["versions"]
    archived = demo_project_files / versions[0]["path"]
    assert result["archived"]["bytes"] == len(b"old-final")
    assert archived.read_bytes() == b"old-final"
    assert previous.read_bytes() == b"final-video"


def test_assemble_project_muxes_generated_voiceover(demo_project_files):
    project = load_project(demo_project_files)
    generate_videos(project, provider_name="mock", dry_run=False)
    from auto_video.pipeline import submit_jobs

    submit_jobs(load_project(demo_project_files), kind="audio", provider_name="mock")
    project = load_project(demo_project_files)
    runner = FakeRenderRunner()

    result = assemble_project(project, runner=runner)

    project = load_project(demo_project_files)
    assert result["voiceover"]["path"] == "renders/final_voice.wav"
    assert result["voiceover"]["segments"][0]["source"] == "generated/audio/S01.wav"
    assert len(runner.commands) == 4
    assert runner.commands[-1][runner.commands[-1].index("-c:a") + 1] == "aac"
    assert project.manifest["renders"]["final"]["voiceover"] == "renders/final_voice.wav"
    assert project.manifest["renders"]["final"]["voiceover_segments"] == 1


def test_assemble_project_dry_run_reports_input_checks(demo_project_files):
    project = load_project(demo_project_files)
    generate_videos(project, provider_name="mock", dry_run=False)
    project = load_project(demo_project_files)

    result = assemble_project(project, dry_run=True)

    assert result["dry_run"] is True
    assert result["checks"][0]["name"] == "clip_ready"
    assert result["checks"][0]["status"] == "ok"


def test_assemble_project_rejects_missing_clip_file(demo_project_files):
    (demo_project_files / "manifest.json").write_text(
        json.dumps(
            {
                "project": "demo_ad",
                "schema_version": "0.1",
                "assets": {},
                "shots": {"S01": {"status": "generated", "clip": "generated/clips/missing.mp4"}},
                "renders": {},
                "jobs": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    project = load_project(demo_project_files)

    with pytest.raises(RenderError) as exc:
        assemble_project(project)

    assert "missing" in str(exc.value)


def test_probe_reports_missing_or_mock_duration(demo_project_files):
    project = load_project(demo_project_files)
    generate_videos(project, provider_name="mock", dry_run=False)
    project = load_project(demo_project_files)

    report = probe_project(project, dry_run=True)
    assert report["dry_run"] is True
    assert report["shots"][0]["id"] == "S01"
    assert report["shots"][0]["manifest_duration"] == 5.0


def test_probe_reports_media_quality_ok(demo_project_files):
    project = load_project(demo_project_files)
    generate_videos(project, provider_name="mock", dry_run=False)
    project = load_project(demo_project_files)
    runner = FakeMediaProbeRunner(_ffprobe_payload())

    report = probe_project(project, runner=runner)

    assert report["summary"]["ok"] == 1
    assert report["summary"]["failed"] == 0
    assert report["shots"][0]["quality_status"] == "ok"
    assert report["shots"][0]["media"]["width"] == 1080
    assert [check["name"] for check in report["shots"][0]["checks"]] == [
        "clip_ready",
        "media_resolution",
        "media_duration",
        "media_fps",
    ]
    assert runner.probed


def test_probe_flags_bad_media_quality(demo_project_files):
    project = load_project(demo_project_files)
    generate_videos(project, provider_name="mock", dry_run=False)
    project = load_project(demo_project_files)
    runner = FakeMediaProbeRunner(_ffprobe_payload(width=640, height=480, duration=1.0, fps="24/1"))

    report = probe_project(project, runner=runner)

    checks = {check["name"]: check for check in report["shots"][0]["checks"]}
    assert report["summary"]["failed"] == 1
    assert report["shots"][0]["quality_status"] == "failed"
    assert checks["media_resolution"]["status"] == "failed"
    assert checks["media_duration"]["status"] == "failed"
    assert checks["media_fps"]["status"] == "failed"


def test_probe_can_run_blackdetect_check(demo_project_files):
    project = load_project(demo_project_files)
    generate_videos(project, provider_name="mock", dry_run=False)
    project = load_project(demo_project_files)
    runner = FakeMediaProbeRunner(
        _ffprobe_payload(duration=5.0),
        blackdetect_stderr="[blackdetect @ 0x1] black_start:0 black_end:4.95 black_duration:4.95\n",
    )

    report = probe_project(project, runner=runner, blackdetect=True, max_black_ratio=0.9)

    blackdetect_check = report["shots"][0]["checks"][-1]
    assert blackdetect_check["name"] == "blackdetect"
    assert blackdetect_check["status"] == "failed"
    assert blackdetect_check["black_ratio"] == 0.99
    assert runner.blackdetected
