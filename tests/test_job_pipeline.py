import json

from auto_video.pipeline import plan_jobs, submit_jobs
from auto_video.project import load_project


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
