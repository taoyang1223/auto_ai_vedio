import pytest

from auto_video.errors import ConfigError
from auto_video.models import AssetRef, ShotPlan


def test_asset_ref_rejects_unknown_role():
    with pytest.raises(ConfigError) as exc:
        AssetRef(path="assets/refs/S01.png", type="image", role="bad_role", usage="preserve_subject")
    assert "role" in str(exc.value)
    assert "bad_role" in str(exc.value)


def test_shot_plan_rejects_non_positive_duration():
    with pytest.raises(ConfigError) as exc:
        ShotPlan(id="S01", duration=0, visual_prompt="test")
    assert "duration" in str(exc.value)
    assert "S01" in str(exc.value)
