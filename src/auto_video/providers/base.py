from __future__ import annotations

from pathlib import Path
from typing import Protocol

from auto_video.jobs import GenerationJob, ProviderResult
from auto_video.models import AssetResult, GenerationTask


class ImageProvider(Protocol):
    name: str

    def generate_image(self, task: GenerationTask) -> AssetResult:
        ...


class VideoProvider(Protocol):
    name: str

    def generate_video(self, task: GenerationTask) -> AssetResult:
        ...


class JobProvider(Protocol):
    name: str

    def execute_job(self, job: GenerationJob, project_root: Path) -> ProviderResult:
        ...
