import json
from pathlib import Path

from auto_video.manifest import ManifestStore
from auto_video.models import AssetResult


def test_manifest_updates_generated_clip(tmp_path: Path):
    store = ManifestStore(tmp_path / "manifest.json", project_name="demo")
    store.record_asset(
        AssetResult(
            shot_id="S01",
            provider="mock",
            path=tmp_path / "generated/clips/S01.mp4",
            kind="clip",
            duration=5.0,
        )
    )
    store.save()

    data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert data["project"] == "demo"
    assert data["shots"]["S01"]["clip"] == "generated/clips/S01.mp4"
    assert data["shots"]["S01"]["duration"] == 5.0
    assert data["shots"]["S01"]["status"] == "generated"


def test_manifest_records_lipsync_clip_without_overwriting_video_provider(tmp_path: Path):
    store = ManifestStore(tmp_path / "manifest.json", project_name="demo")
    store.record_asset(
        AssetResult(
            shot_id="S01",
            provider="comfyui_wan",
            path=tmp_path / "generated/clips/S01.mp4",
            kind="clip",
            duration=5.0,
        )
    )
    store.record_asset(
        AssetResult(
            shot_id="S01",
            provider="comfyui_lipsync",
            path=tmp_path / "generated/lipsync/S01.mp4",
            kind="lipsync_clip",
            duration=5.0,
        )
    )
    store.save()

    data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    shot = data["shots"]["S01"]
    assert shot["clip"] == "generated/clips/S01.mp4"
    assert shot["lipsync_clip"] == "generated/lipsync/S01.mp4"
    assert shot["provider"] == "comfyui_wan"
    assert shot["lipsync_provider"] == "comfyui_lipsync"


def test_manifest_records_failed_task(tmp_path: Path):
    store = ManifestStore(tmp_path / "manifest.json", project_name="demo")
    store.record_asset(
        AssetResult(
            shot_id="S03",
            provider="seedance",
            path=tmp_path / "generated/clips/S03.mp4",
            kind="clip",
            status="failed",
            error="SetLimitExceeded",
            retryable=True,
        )
    )
    store.save()

    data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert data["shots"]["S03"]["status"] == "failed"
    assert data["shots"]["S03"]["error"] == "SetLimitExceeded"
    assert data["shots"]["S03"]["retryable"] is True
