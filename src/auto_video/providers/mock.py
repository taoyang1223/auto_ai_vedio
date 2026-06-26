from __future__ import annotations

from auto_video.models import AssetResult, GenerationTask


class MockProvider:
    name = "mock"

    def generate_image(self, task: GenerationTask) -> AssetResult:
        task.output_path.parent.mkdir(parents=True, exist_ok=True)
        task.output_path.write_text(f"mock image for {task.shot.id}\n{task.prompt}\n", encoding="utf-8")
        return AssetResult(shot_id=task.shot.id, provider=self.name, path=task.output_path, kind="image")

    def generate_video(self, task: GenerationTask) -> AssetResult:
        task.output_path.parent.mkdir(parents=True, exist_ok=True)
        task.output_path.write_text(f"mock video for {task.shot.id}\n{task.prompt}\n", encoding="utf-8")
        return AssetResult(
            shot_id=task.shot.id,
            provider=self.name,
            path=task.output_path,
            kind="clip",
            duration=task.shot.duration,
        )
