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
    assert project.manifest["renders"]["final"]["path"] == "renders/final.mp4"


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
