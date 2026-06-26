from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigError

ASSET_TYPES = {"image", "video", "audio", "text"}
REFERENCE_ROLES = {
    "first_frame",
    "last_frame",
    "style_reference",
    "camera_reference",
    "motion_reference",
    "voice_reference",
    "bgm_reference",
    "environment_reference",
}
REFERENCE_USAGES = {
    "preserve_subject",
    "preserve_voice",
    "extract_style",
    "extract_camera_motion",
    "extract_action",
    "extract_audio_rhythm",
    "provide_context",
}
PROVIDERS = {"mock", "seedream", "seedance", "wan", "slideshow"}


def _require_enum(value: str, allowed: set[str], field_name: str) -> None:
    if value not in allowed:
        allowed_list = ", ".join(sorted(allowed))
        raise ConfigError(
            f"{field_name} has unsupported value {value!r}; allowed values: {allowed_list}",
            fix=f"Use one of: {allowed_list}.",
        )


@dataclass(frozen=True)
class AssetRef:
    path: str
    type: str
    role: str
    usage: str

    def __post_init__(self) -> None:
        _require_enum(self.type, ASSET_TYPES, "type")
        _require_enum(self.role, REFERENCE_ROLES, "role")
        _require_enum(self.usage, REFERENCE_USAGES, "usage")


@dataclass(frozen=True)
class RenderTransition:
    type: str = "fade"
    duration: float = 0.6


@dataclass(frozen=True)
class RenderText:
    text: str
    at: float


@dataclass(frozen=True)
class RenderConfig:
    transition: RenderTransition = field(default_factory=RenderTransition)
    bgm: str | None = None
    bgm_volume: float = 0.2
    subtitle_style: str = "default"
    brand: RenderText | None = None
    cta: RenderText | None = None


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    root: Path
    aspect_ratio: str = "9:16"
    width: int = 1080
    height: int = 1920
    fps: int = 30
    default_video_provider: str = "mock"
    default_image_provider: str = "mock"
    default_audio_provider: str = "mock"
    render: RenderConfig = field(default_factory=RenderConfig)

    def __post_init__(self) -> None:
        for field_name, provider in {
            "default_video_provider": self.default_video_provider,
            "default_image_provider": self.default_image_provider,
            "default_audio_provider": self.default_audio_provider,
        }.items():
            _require_enum(provider, PROVIDERS, field_name)


@dataclass(frozen=True)
class ShotPlan:
    id: str
    duration: float
    visual_prompt: str = ""
    title: str = ""
    intent: str = ""
    provider: str | None = None
    camera_motion: str = ""
    environment_motion: str = ""
    performance: str = ""
    lighting: str = ""
    audio_intent: str = ""
    subtitle: str = ""
    negative_prompt: str = ""
    refs: tuple[AssetRef, ...] = ()

    def __post_init__(self) -> None:
        if self.duration <= 0:
            raise ConfigError(
                f"shot {self.id} duration must be greater than 0; got {self.duration}",
                fix="Set duration to a positive number of seconds.",
            )
        if self.provider is not None:
            _require_enum(self.provider, PROVIDERS, f"shot {self.id} provider")


@dataclass(frozen=True)
class Project:
    config: ProjectConfig
    shots: tuple[ShotPlan, ...]
    manifest: dict[str, Any]


@dataclass(frozen=True)
class GenerationTask:
    project: ProjectConfig
    shot: ShotPlan
    prompt: str
    output_path: Path
    dry_run: bool = False


@dataclass(frozen=True)
class AssetResult:
    shot_id: str
    provider: str
    path: Path
    kind: str
    duration: float | None = None
    status: str = "generated"
    error: str | None = None
    retryable: bool = False
