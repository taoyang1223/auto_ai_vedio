from __future__ import annotations

from typing import Protocol

from auto_video.models import AssetResult, GenerationTask


class ImageProvider(Protocol):
    name: str

    def generate_image(self, task: GenerationTask) -> AssetResult:
        ...


class VideoProvider(Protocol):
    name: str

    def generate_video(self, task: GenerationTask) -> AssetResult:
        ...
