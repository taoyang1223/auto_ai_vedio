import json
import shutil

from auto_video.project import load_project
from auto_video.worker_bundle import export_worker_bundle
from auto_video.worker_runner import run_worker_bundle


def test_run_worker_bundle_writes_outputs_result_and_log(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    bundle = tmp_path / "bundle"
    export_worker_bundle(project, bundle, kind="video", provider_name="mock")

    result = run_worker_bundle(bundle)

    output = bundle / "outputs" / "generated" / "clips" / "S01.mp4"
    result_json = json.loads((bundle / "result.json").read_text(encoding="utf-8"))
    assert result["results"][0]["job_id"] == "demo_ad:S01:video:mock"
    assert output.read_text(encoding="utf-8").startswith("mock video")
    assert result_json["results"][0]["path"] == "outputs/generated/clips/S01.mp4"
    assert (bundle / "logs" / "worker.log").read_text(encoding="utf-8").startswith("started")


def test_run_worker_bundle_does_not_need_source_project(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    bundle = tmp_path / "bundle"
    export_worker_bundle(project, bundle, kind="video", provider_name="mock")
    shutil.rmtree(demo_project_files)

    result = run_worker_bundle(bundle)

    assert result["results"][0]["status"] == "succeeded"
    assert (bundle / "outputs" / "generated" / "clips" / "S01.mp4").exists()
