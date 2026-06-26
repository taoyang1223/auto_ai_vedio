import json

from auto_video.job_builder import build_jobs
from auto_video.job_store import JobStore
from auto_video.jobs import ProviderResult
from auto_video.project import load_project


def test_job_store_persists_planned_job(demo_project_files):
    project = load_project(demo_project_files)
    job = build_jobs(project, kind="video", provider_name="mock")[0]
    store = JobStore(demo_project_files / "manifest.json", project_name=project.config.name)

    store.record_job(job)
    store.save()

    data = json.loads((demo_project_files / "manifest.json").read_text(encoding="utf-8"))
    assert "jobs" in data
    assert data["jobs"]["demo_ad:S01:video:mock"]["status"] == "planned"
    assert data["jobs"]["demo_ad:S01:video:mock"]["output_path"] == "generated/clips/S01.mp4"


def test_job_store_records_success_result_and_legacy_clip(demo_project_files):
    project = load_project(demo_project_files)
    job = build_jobs(project, kind="video", provider_name="mock")[0]
    clip = demo_project_files / "generated" / "clips" / "S01.mp4"
    store = JobStore(demo_project_files / "manifest.json", project_name=project.config.name)

    store.record_job(job)
    store.record_result(
        ProviderResult(
            job_id=job.id,
            shot_id="S01",
            kind="video",
            provider="mock",
            status="succeeded",
            path=clip,
            duration=5.0,
        )
    )
    store.save()

    data = json.loads((demo_project_files / "manifest.json").read_text(encoding="utf-8"))
    assert data["jobs"][job.id]["status"] == "succeeded"
    assert data["jobs"][job.id]["attempts"] == 1
    assert data["shots"]["S01"]["clip"] == "generated/clips/S01.mp4"
    assert data["shots"]["S01"]["status"] == "generated"


def test_job_store_records_retryable_failure_without_clip(demo_project_files):
    project = load_project(demo_project_files)
    job = build_jobs(project, kind="video", provider_name="mock")[0]
    store = JobStore(demo_project_files / "manifest.json", project_name=project.config.name)

    store.record_job(job)
    store.record_result(
        ProviderResult(
            job_id=job.id,
            shot_id="S01",
            kind="video",
            provider="mock",
            status="retryable_failed",
            error="RateLimit",
            retryable=True,
        )
    )
    store.save()

    data = json.loads((demo_project_files / "manifest.json").read_text(encoding="utf-8"))
    assert data["jobs"][job.id]["status"] == "retryable_failed"
    assert data["jobs"][job.id]["error"] == "RateLimit"
    assert data["jobs"][job.id]["retryable"] is True
    assert "clip" not in data.get("shots", {}).get("S01", {})
