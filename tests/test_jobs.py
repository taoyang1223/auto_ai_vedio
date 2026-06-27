from pathlib import Path

import pytest

from auto_video.errors import ConfigError
from auto_video.jobs import (
    GenerationJob,
    ProviderControls,
    ProviderReference,
    ProviderResult,
    make_job_id,
    relative_output_path,
)


def test_make_job_id_is_stable():
    assert make_job_id("demo_ad", "S01", "video", "mock") == "demo_ad:S01:video:mock"


def test_generation_job_round_trips_to_manifest_dict():
    job = GenerationJob(
        id="demo_ad:S01:video:mock",
        project_name="demo_ad",
        shot_id="S01",
        kind="video",
        provider="mock",
        prompt="A tired person at a cold desk",
        negative_prompt="text, watermark",
        duration=5.0,
        output_path="generated/clips/S01.mp4",
        refs=(
            ProviderReference(
                path="assets/refs/S01.txt",
                type="text",
                role="first_frame",
                usage="preserve_subject",
                exists=True,
            ),
        ),
        controls=ProviderControls(
            visual_prompt="A tired person at a cold desk",
            camera_motion="slow_dolly_in",
            environment_motion="screen flicker",
            performance="tired breathing",
            lighting="cold fluorescent light",
            audio_intent="quiet room tone",
            subtitle="Late night again",
            negative_prompt="text, watermark",
            aspect_ratio="9:16",
            width=1080,
            height=1920,
            fps=30,
        ),
        created_at="2026-06-26T00:00:00Z",
        updated_at="2026-06-26T00:00:00Z",
    )

    data = job.to_dict()
    restored = GenerationJob.from_dict(data)

    assert data["id"] == "demo_ad:S01:video:mock"
    assert data["refs"][0]["role"] == "first_frame"
    assert data["controls"]["camera_motion"] == "slow_dolly_in"
    assert restored == job


def test_provider_result_maps_video_to_legacy_clip_asset():
    result = ProviderResult(
        job_id="demo_ad:S01:video:mock",
        shot_id="S01",
        kind="video",
        provider="mock",
        status="succeeded",
        path=Path("/tmp/demo/generated/clips/S01.mp4"),
        duration=5.0,
    )

    asset = result.to_asset_result()

    assert asset.kind == "clip"
    assert asset.status == "generated"
    assert asset.path == Path("/tmp/demo/generated/clips/S01.mp4")


def test_relative_output_path_uses_expected_kind_directories():
    assert relative_output_path("S01", "image") == "generated/images/S01.png"
    assert relative_output_path("S01", "video") == "generated/clips/S01.mp4"
    assert relative_output_path("S01", "audio") == "generated/audio/S01.wav"


def test_invalid_job_kind_is_config_error():
    with pytest.raises(ConfigError) as exc:
        relative_output_path("S01", "mesh")
    assert "job kind" in str(exc.value)
