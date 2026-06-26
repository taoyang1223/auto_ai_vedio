from __future__ import annotations

from pathlib import Path

from auto_video.jobs import GenerationJob, ProviderResult
from auto_video.models import AssetResult, GenerationTask


class MockProvider:
    name = "mock"

    def execute_job(self, job: GenerationJob, project_root: Path) -> ProviderResult:
        output_path = project_root / job.output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if job.kind == "image":
            output_path.write_text(f"mock image for {job.shot_id}\n{job.prompt}\n", encoding="utf-8")
            duration = None
        elif job.kind == "video":
            output_path.write_text(f"mock video for {job.shot_id}\n{job.prompt}\n", encoding="utf-8")
            duration = job.duration
        else:
            output_path.write_text(f"mock audio for {job.shot_id}\n{job.prompt}\n", encoding="utf-8")
            duration = job.duration
        return ProviderResult(
            job_id=job.id,
            shot_id=job.shot_id,
            kind=job.kind,
            provider=self.name,
            status="succeeded",
            path=output_path,
            duration=duration,
            metadata={"mock": True},
        )

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
