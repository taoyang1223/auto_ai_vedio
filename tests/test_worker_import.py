import json

from auto_video.project import load_project
from auto_video.worker_bundle import export_worker_bundle, import_worker_results
from auto_video.worker_runner import run_worker_bundle


def test_import_worker_results_copies_output_and_updates_manifest(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    bundle = tmp_path / "bundle"
    export_worker_bundle(project, bundle, kind="video", provider_name="mock")
    run_worker_bundle(bundle)

    summary = import_worker_results(demo_project_files, bundle)

    manifest = json.loads((demo_project_files / "manifest.json").read_text(encoding="utf-8"))
    assert summary["imported"] == ["demo_ad:S01:video:mock"]
    assert (demo_project_files / "generated" / "clips" / "S01.mp4").exists()
    assert manifest["jobs"]["demo_ad:S01:video:mock"]["status"] == "succeeded"
    assert manifest["shots"]["S01"]["clip"] == "generated/clips/S01.mp4"


def test_import_worker_failure_records_job_without_legacy_clip(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    bundle = tmp_path / "bundle"
    export_worker_bundle(project, bundle, kind="video", provider_name="mock")
    (bundle / "result.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "project": "demo_ad",
                "results": [
                    {
                        "job_id": "demo_ad:S01:video:mock",
                        "shot_id": "S01",
                        "kind": "video",
                        "provider": "mock",
                        "status": "retryable_failed",
                        "path": None,
                        "duration": None,
                        "provider_job_id": None,
                        "error": "NoGPU",
                        "retryable": True,
                        "metadata": {"worker": "local"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    summary = import_worker_results(demo_project_files, bundle)

    manifest = json.loads((demo_project_files / "manifest.json").read_text(encoding="utf-8"))
    assert summary["failed"] == ["demo_ad:S01:video:mock"]
    assert manifest["jobs"]["demo_ad:S01:video:mock"]["status"] == "retryable_failed"
    assert manifest["jobs"]["demo_ad:S01:video:mock"]["error"] == "NoGPU"
    assert "clip" not in manifest["shots"]["S01"]
