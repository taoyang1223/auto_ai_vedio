import json
import os

from auto_video.pipeline import plan_jobs, submit_jobs
from auto_video.project import load_project


def _make_two_shot_project(project):
    (project / "shots.json").write_text(
        json.dumps(
            {
                "shots": [
                    {
                        "id": "S01",
                        "title": "Hook",
                        "duration": 5,
                        "visual_prompt": "A tired person at a cold desk",
                    },
                    {
                        "id": "S02",
                        "title": "Payoff",
                        "duration": 4,
                        "visual_prompt": "The same person smiles at sunrise",
                    },
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_plan_jobs_does_not_write_manifest(demo_project_files):
    project = load_project(demo_project_files)

    plan = plan_jobs(project, kind="video", provider_name="mock")

    assert plan["dry_run"] is True
    assert plan["planned"][0]["id"] == "demo_ad:S01:video:mock"
    assert plan["planned"][0]["output_path"] == "generated/clips/S01.mp4"
    assert not (demo_project_files / "manifest.json").exists()


def test_submit_jobs_writes_clip_and_job_manifest(demo_project_files):
    project = load_project(demo_project_files)

    results = submit_jobs(project, kind="video", provider_name="mock")

    manifest = json.loads((demo_project_files / "manifest.json").read_text(encoding="utf-8"))
    assert results[0].job_id == "demo_ad:S01:video:mock"
    assert manifest["shots"]["S01"]["clip"] == "generated/clips/S01.mp4"
    assert manifest["jobs"]["demo_ad:S01:video:mock"]["status"] == "succeeded"


def test_plan_jobs_failed_only_selects_failed_manifest_jobs(demo_project_files):
    _make_two_shot_project(demo_project_files)
    (demo_project_files / "manifest.json").write_text(
        json.dumps(
            {
                "project": "demo_ad",
                "schema_version": "0.1",
                "assets": {},
                "shots": {},
                "renders": {},
                "jobs": {
                    "demo_ad:S01:video:mock": {"status": "succeeded"},
                    "demo_ad:S02:video:mock": {"status": "retryable_failed"},
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    project = load_project(demo_project_files)

    plan = plan_jobs(project, kind="video", provider_name="mock", failed_only=True)

    assert [job["shot_id"] for job in plan["planned"]] == ["S02"]


def test_plan_jobs_skip_succeeded_keeps_unfinished_jobs(demo_project_files):
    _make_two_shot_project(demo_project_files)
    (demo_project_files / "manifest.json").write_text(
        json.dumps(
            {
                "project": "demo_ad",
                "schema_version": "0.1",
                "assets": {},
                "shots": {},
                "renders": {},
                "jobs": {
                    "demo_ad:S01:video:mock": {"status": "succeeded"},
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    output = demo_project_files / "generated" / "clips" / "S01.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("finished clip", encoding="utf-8")
    project = load_project(demo_project_files)

    plan = plan_jobs(project, kind="video", provider_name="mock", skip_succeeded=True)

    assert [job["shot_id"] for job in plan["planned"]] == ["S02"]


def test_plan_jobs_skip_succeeded_reruns_missing_output(demo_project_files):
    (demo_project_files / "manifest.json").write_text(
        json.dumps(
            {
                "project": "demo_ad",
                "schema_version": "0.1",
                "assets": {},
                "shots": {},
                "renders": {},
                "jobs": {
                    "demo_ad:S01:video:mock": {"status": "succeeded"},
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    project = load_project(demo_project_files)

    plan = plan_jobs(project, kind="video", provider_name="mock", skip_succeeded=True)

    assert [job["shot_id"] for job in plan["planned"]] == ["S01"]


def test_plan_jobs_skip_succeeded_reruns_stale_output(demo_project_files):
    output = demo_project_files / "generated" / "clips" / "S01.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("old clip", encoding="utf-8")
    ref = demo_project_files / "assets" / "refs" / "S01.txt"
    os.utime(output, (1000, 1000))
    os.utime(ref, (2000, 2000))
    (demo_project_files / "manifest.json").write_text(
        json.dumps(
            {
                "project": "demo_ad",
                "schema_version": "0.1",
                "assets": {},
                "shots": {},
                "renders": {},
                "jobs": {
                    "demo_ad:S01:video:mock": {"status": "succeeded"},
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    project = load_project(demo_project_files)

    plan = plan_jobs(project, kind="video", provider_name="mock", skip_succeeded=True)

    assert [job["shot_id"] for job in plan["planned"]] == ["S01"]


def test_submit_jobs_failed_only_reruns_failed_job(demo_project_files):
    _make_two_shot_project(demo_project_files)
    (demo_project_files / "manifest.json").write_text(
        json.dumps(
            {
                "project": "demo_ad",
                "schema_version": "0.1",
                "assets": {},
                "shots": {},
                "renders": {},
                "jobs": {
                    "demo_ad:S01:video:mock": {"status": "succeeded", "attempts": 1},
                    "demo_ad:S02:video:mock": {"status": "failed", "attempts": 1, "error": "NoGPU"},
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    project = load_project(demo_project_files)

    results = submit_jobs(project, kind="video", provider_name="mock", failed_only=True)

    manifest = json.loads((demo_project_files / "manifest.json").read_text(encoding="utf-8"))
    assert [result.shot_id for result in results] == ["S02"]
    assert manifest["jobs"]["demo_ad:S01:video:mock"]["status"] == "succeeded"
    assert manifest["jobs"]["demo_ad:S02:video:mock"]["status"] == "succeeded"
    assert manifest["shots"]["S02"]["clip"] == "generated/clips/S02.mp4"
