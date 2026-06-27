import json
from pathlib import Path

from auto_video.cli import main
from auto_video.continuity import build_tail_frame_tasks, extract_tail_frames
from auto_video.job_builder import build_jobs
from auto_video.project import load_project


class FakeTailFrameExtractor:
    def __init__(self):
        self.calls: list[tuple[Path, Path]] = []

    def extract(self, clip: Path, output: Path) -> None:
        self.calls.append((clip, output))
        output.write_bytes(b"fake-png")


def _make_continuity_project(project: Path) -> None:
    (project / "shots.json").write_text(
        json.dumps(
            {
                "shots": [
                    {"id": "S01", "duration": 5, "visual_prompt": "Opening shot"},
                    {"id": "S02", "duration": 4, "visual_prompt": "Continuation shot"},
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    clip = project / "generated" / "clips" / "S01.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"fake-video")
    (project / "manifest.json").write_text(
        json.dumps(
            {
                "project": "demo_ad",
                "schema_version": "0.1",
                "assets": {},
                "shots": {
                    "S01": {
                        "status": "generated",
                        "provider": "mock",
                        "clip": "generated/clips/S01.mp4",
                        "duration": 5,
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


def test_build_tail_frame_tasks_pairs_adjacent_shots(demo_project_files):
    _make_continuity_project(demo_project_files)
    project = load_project(demo_project_files)

    tasks = build_tail_frame_tasks(project)

    assert len(tasks) == 1
    assert tasks[0].shot_id == "S01"
    assert tasks[0].next_shot_id == "S02"
    assert tasks[0].clip == demo_project_files / "generated" / "clips" / "S01.mp4"
    assert tasks[0].output == demo_project_files / "assets" / "continuity" / "S01_tail.png"


def test_extract_tail_frames_records_continuity_refs(demo_project_files):
    _make_continuity_project(demo_project_files)
    extractor = FakeTailFrameExtractor()
    project = load_project(demo_project_files)

    result = extract_tail_frames(project, extractor=extractor)

    output = demo_project_files / "assets" / "continuity" / "S01_tail.png"
    manifest = json.loads((demo_project_files / "manifest.json").read_text(encoding="utf-8"))
    assert result["extracted"] == [
        {
            "shot_id": "S01",
            "next_shot_id": "S02",
            "clip": "generated/clips/S01.mp4",
            "output": "assets/continuity/S01_tail.png",
        }
    ]
    assert extractor.calls == [(demo_project_files / "generated" / "clips" / "S01.mp4", output)]
    assert output.read_bytes() == b"fake-png"
    assert manifest["shots"]["S01"]["tail_frame"] == "assets/continuity/S01_tail.png"
    assert manifest["shots"]["S02"]["continuity_refs"][0]["path"] == "assets/continuity/S01_tail.png"


def test_job_builder_injects_manifest_continuity_refs_before_static_refs(demo_project_files):
    _make_continuity_project(demo_project_files)
    extract_tail_frames(load_project(demo_project_files), extractor=FakeTailFrameExtractor())
    project = load_project(demo_project_files)

    jobs = build_jobs(project, kind="video", provider_name="mock")

    s02 = next(job for job in jobs if job.shot_id == "S02")
    assert s02.refs[0].path == "assets/continuity/S01_tail.png"
    assert s02.refs[0].type == "image"
    assert s02.refs[0].role == "first_frame"
    assert s02.refs[0].usage == "preserve_subject"
    assert s02.refs[0].exists is True


def test_extract_tail_frames_dry_run_does_not_write_manifest(demo_project_files):
    _make_continuity_project(demo_project_files)
    before = (demo_project_files / "manifest.json").read_text(encoding="utf-8")
    project = load_project(demo_project_files)

    result = extract_tail_frames(project, extractor=FakeTailFrameExtractor(), dry_run=True)

    assert result["dry_run"] is True
    assert result["planned"][0]["output"] == "assets/continuity/S01_tail.png"
    assert not (demo_project_files / "assets" / "continuity" / "S01_tail.png").exists()
    assert (demo_project_files / "manifest.json").read_text(encoding="utf-8") == before


def test_continuity_cli_dry_run_prints_plan(demo_project_files, capsys):
    _make_continuity_project(demo_project_files)

    assert main(["continuity", "extract-tail-frames", str(demo_project_files), "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["dry_run"] is True
    assert payload["planned"][0]["shot_id"] == "S01"
