import json

import pytest

from auto_video.errors import ConfigError
from auto_video.project import load_project
from auto_video.worker_bundle import export_worker_bundle, safe_bundle_filename


def test_safe_bundle_filename_replaces_unsafe_job_id_chars():
    assert safe_bundle_filename("demo_ad:S01:video:mock") == "demo_ad_S01_video_mock.json"


def test_export_worker_bundle_creates_layout_and_copies_refs(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    bundle = tmp_path / "bundle"

    summary = export_worker_bundle(project, bundle, kind="video", provider_name="mock")

    assert summary["project"] == "demo_ad"
    assert summary["jobs"] == ["jobs/demo_ad_S01_video_mock.json"]
    assert (bundle / "bundle.json").exists()
    assert (bundle / "project.yaml").exists()
    assert (bundle / "shots.json").exists()
    assert (bundle / "jobs" / "demo_ad_S01_video_mock.json").exists()
    assert (bundle / "refs" / "S01" / "assets_refs_S01.txt").read_text(encoding="utf-8") == "mock ref"
    assert (bundle / "outputs").is_dir()
    assert (bundle / "logs").is_dir()
    assert not (demo_project_files / "manifest.json").exists()

    index = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    assert index["refs"][0]["source"] == "assets/refs/S01.txt"
    assert index["refs"][0]["bundle_path"] == "refs/S01/assets_refs_S01.txt"


def test_export_rejects_existing_non_empty_bundle_without_force(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "keep.txt").write_text("do not remove", encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        export_worker_bundle(project, bundle, kind="video", provider_name="mock")

    assert "already exists" in str(exc.value)
    assert (bundle / "keep.txt").exists()


def test_export_force_replaces_existing_bundle(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "old.txt").write_text("old", encoding="utf-8")

    export_worker_bundle(project, bundle, kind="video", provider_name="mock", force=True)

    assert not (bundle / "old.txt").exists()
    assert (bundle / "bundle.json").exists()


def test_export_rejects_project_root_as_bundle_even_with_force(demo_project_files):
    project = load_project(demo_project_files)

    with pytest.raises(ConfigError) as exc:
        export_worker_bundle(project, demo_project_files, kind="video", provider_name="mock", force=True)

    assert "project root" in str(exc.value)
    assert (demo_project_files / "project.yaml").exists()
