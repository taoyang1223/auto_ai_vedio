import base64

from auto_video.asset_library import list_asset_library, upload_library_asset
from auto_video.project import load_project


def test_asset_library_uploads_and_lists_project_assets(demo_project_files):
    asset = upload_library_asset(
        demo_project_files,
        {
            "label": "主角参考",
            "type": "image",
            "role": "style_reference",
            "usage": "preserve_subject",
            "filename": "hero.png",
            "data_base64": base64.b64encode(b"fake-image").decode("ascii"),
        },
    )

    assets = list_asset_library(load_project(demo_project_files))

    uploaded = next(item for item in assets if item["id"] == asset["id"])
    implicit = next(item for item in assets if item["path"] == "assets/refs/S01.txt")
    assert uploaded["label"] == "主角参考"
    assert uploaded["type"] == "image"
    assert uploaded["exists"] is True
    assert uploaded["bound_shots"] == []
    assert implicit["type"] == "text"
    assert implicit["bound_shots"] == ["S01"]
