import json
import shutil

import pytest

from auto_video.first_frame_generation import _placeholder_png, generate_first_frames, promote_generated_images_to_first_frames
from auto_video.job_builder import build_jobs
from auto_video.project import load_project


def _png_size(path):
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def test_image_jobs_use_saved_first_frame_prompt(demo_project_files):
    (demo_project_files / "assets" / "first_frame_prompts.json").write_text(
        json.dumps(
            {
                "prompts": [
                    {
                        "shot_id": "S01",
                        "prompt": "custom first frame still",
                        "negative_prompt": "bad frame",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    project = load_project(demo_project_files)

    job = build_jobs(project, kind="image", provider_name="mock")[0]

    assert job.prompt == "custom first frame still"
    assert job.negative_prompt == "bad frame"


def test_image_jobs_use_default_image_provider_not_shot_video_provider(demo_project_files):
    data = json.loads((demo_project_files / "shots.json").read_text(encoding="utf-8"))
    data["shots"][0]["provider"] = "video_only_provider"
    (demo_project_files / "shots.json").write_text(json.dumps(data), encoding="utf-8")
    project = load_project(demo_project_files)

    image_job = build_jobs(project, kind="image")[0]
    video_job = build_jobs(project, kind="video")[0]

    assert image_job.provider == "mock"
    assert video_job.provider == "video_only_provider"


def test_generate_first_frames_promotes_mock_output_to_png_ref(demo_project_files):
    project = load_project(demo_project_files)

    result = generate_first_frames(project, provider_name="mock", only={"S01"})
    reloaded = load_project(demo_project_files)

    output = demo_project_files / "assets" / "refs" / "S01_first_frame.png"
    manifest = json.loads((demo_project_files / "manifest.json").read_text(encoding="utf-8"))

    assert result["count"] == 1
    assert result["first_frames"]["count"] == 1
    assert result["first_frames"]["promoted"][0]["path"] == "assets/refs/S01_first_frame.png"
    assert _png_size(output) == (1080, 1920)
    assert manifest["shots"]["S01"]["image"] == "generated/images/S01.png"
    assert reloaded.shots[0].refs[0].path == "assets/refs/S01_first_frame.png"
    assert reloaded.shots[0].refs[0].type == "image"


def test_promoted_generated_image_is_normalized_to_project_size(demo_project_files):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is required for image normalization")
    generated = demo_project_files / "generated" / "images" / "S01.png"
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_bytes(_placeholder_png(3132, 2048, seed="wide-source"))
    (demo_project_files / "manifest.json").write_text(
        json.dumps({"shots": {"S01": {"image": "generated/images/S01.png"}}}, indent=2),
        encoding="utf-8",
    )
    project = load_project(demo_project_files)

    result = promote_generated_images_to_first_frames(project, only={"S01"})

    output = demo_project_files / "assets" / "refs" / "S01_first_frame.png"
    assert result["promoted"][0]["normalized"] is True
    assert _png_size(output) == (1080, 1920)
