from pathlib import Path

import pytest


@pytest.fixture
def demo_project_files(tmp_path: Path) -> Path:
    project = tmp_path / "demo"
    (project / "assets" / "refs").mkdir(parents=True)
    (project / "assets" / "refs" / "S01.txt").write_text("mock ref", encoding="utf-8")
    (project / "project.yaml").write_text(
        """
name: demo_ad
aspect_ratio: "9:16"
width: 1080
height: 1920
fps: 30
default_video_provider: mock
default_image_provider: mock
default_audio_provider: mock
render:
  transition:
    type: fade
    duration: 0.6
  bgm_volume: 0.2
""".strip(),
        encoding="utf-8",
    )
    (project / "shots.json").write_text(
        """
{
  "shots": [
    {
      "id": "S01",
      "title": "Hook",
      "duration": 5,
      "visual_prompt": "A tired person at a cold desk",
      "camera_motion": "slow_dolly_in",
      "environment_motion": "screen flicker",
      "performance": "tired breathing",
      "lighting": "cold fluorescent light",
      "audio_intent": "quiet room tone",
      "subtitle": "Late night again",
      "negative_prompt": "text, watermark",
      "refs": [
        {
          "path": "assets/refs/S01.txt",
          "type": "text",
          "role": "first_frame",
          "usage": "preserve_subject"
        }
      ]
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    return project
