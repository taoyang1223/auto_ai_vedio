from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import ConfigError, ProviderError
from .models import AssetResult

JOB_KINDS = {"image", "video", "audio"}
JOB_STATUSES = {"planned", "queued", "running", "succeeded", "failed", "retryable_failed"}


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _require_value(value: str, allowed: set[str], field_name: str) -> None:
    if value not in allowed:
        allowed_list = ", ".join(sorted(allowed))
        raise ConfigError(
            f"{field_name} has unsupported value {value!r}; allowed values: {allowed_list}",
            fix=f"Use one of: {allowed_list}.",
        )


def make_job_id(project_name: str, shot_id: str, kind: str, provider: str) -> str:
    _require_value(kind, JOB_KINDS, "job kind")
    return f"{project_name}:{shot_id}:{kind}:{provider}"


def relative_output_path(shot_id: str, kind: str) -> str:
    _require_value(kind, JOB_KINDS, "job kind")
    if kind == "image":
        return f"generated/images/{shot_id}.png"
    if kind == "video":
        return f"generated/clips/{shot_id}.mp4"
    return f"generated/audio/{shot_id}.wav"


def legacy_asset_kind(kind: str) -> str:
    _require_value(kind, JOB_KINDS, "job kind")
    if kind == "video":
        return "clip"
    return kind


@dataclass(frozen=True)
class ProviderReference:
    path: str
    type: str
    role: str
    usage: str
    exists: bool
    updated_at: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderReference":
        raw_updated_at = data.get("updated_at")
        return cls(
            path=str(data["path"]),
            type=str(data["type"]),
            role=str(data["role"]),
            usage=str(data["usage"]),
            exists=bool(data["exists"]),
            updated_at=float(raw_updated_at) if raw_updated_at is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderControls:
    visual_prompt: str
    camera_motion: str
    environment_motion: str
    performance: str
    lighting: str
    audio_intent: str
    subtitle: str
    negative_prompt: str
    aspect_ratio: str
    width: int
    height: int
    fps: int
    characters: tuple[str, ...] = ()
    scene: str = ""
    speaker: str = ""
    voice: str = ""
    wardrobe: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderControls":
        return cls(
            visual_prompt=str(data.get("visual_prompt", "")),
            characters=tuple(str(item) for item in data.get("characters", []) if str(item).strip()),
            scene=str(data.get("scene", "")),
            speaker=str(data.get("speaker", "")),
            voice=str(data.get("voice", "")),
            wardrobe=str(data.get("wardrobe", "")),
            camera_motion=str(data.get("camera_motion", "")),
            environment_motion=str(data.get("environment_motion", "")),
            performance=str(data.get("performance", "")),
            lighting=str(data.get("lighting", "")),
            audio_intent=str(data.get("audio_intent", "")),
            subtitle=str(data.get("subtitle", "")),
            negative_prompt=str(data.get("negative_prompt", "")),
            aspect_ratio=str(data.get("aspect_ratio", "9:16")),
            width=int(data.get("width", 1080)),
            height=int(data.get("height", 1920)),
            fps=int(data.get("fps", 30)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GenerationJob:
    id: str
    project_name: str
    shot_id: str
    kind: str
    provider: str
    prompt: str
    negative_prompt: str
    duration: float | None
    output_path: str
    output_exists: bool = False
    output_updated_at: float | None = None
    refs: tuple[ProviderReference, ...] = ()
    controls: ProviderControls | None = None
    status: str = "planned"
    attempts: int = 0
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    provider_job_id: str | None = None
    error: str | None = None
    retryable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_value(self.kind, JOB_KINDS, "job kind")
        _require_value(self.status, JOB_STATUSES, "job status")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GenerationJob":
        controls_data = data.get("controls")
        return cls(
            id=str(data["id"]),
            project_name=str(data["project_name"]),
            shot_id=str(data["shot_id"]),
            kind=str(data["kind"]),
            provider=str(data["provider"]),
            prompt=str(data.get("prompt", "")),
            negative_prompt=str(data.get("negative_prompt", "")),
            duration=float(data["duration"]) if data.get("duration") is not None else None,
            output_path=str(data["output_path"]),
            output_exists=bool(data.get("output_exists", False)),
            output_updated_at=float(data["output_updated_at"]) if data.get("output_updated_at") is not None else None,
            refs=tuple(ProviderReference.from_dict(ref) for ref in data.get("refs", [])),
            controls=ProviderControls.from_dict(controls_data) if controls_data else None,
            status=str(data.get("status", "planned")),
            attempts=int(data.get("attempts", 0)),
            created_at=str(data["created_at"]) if data.get("created_at") else utc_now_iso(),
            updated_at=str(data["updated_at"]) if data.get("updated_at") else utc_now_iso(),
            provider_job_id=data.get("provider_job_id"),
            error=data.get("error"),
            retryable=bool(data.get("retryable", False)),
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "shot_id": self.shot_id,
            "kind": self.kind,
            "provider": self.provider,
            "status": self.status,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "duration": self.duration,
            "output_path": self.output_path,
            "output_exists": self.output_exists,
            "output_updated_at": self.output_updated_at,
            "refs": [ref.to_dict() for ref in self.refs],
            "controls": self.controls.to_dict() if self.controls else None,
            "attempts": self.attempts,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "provider_job_id": self.provider_job_id,
            "error": self.error,
            "retryable": self.retryable,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ProviderResult:
    job_id: str
    shot_id: str
    kind: str
    provider: str
    status: str
    path: Path | None = None
    duration: float | None = None
    provider_job_id: str | None = None
    error: str | None = None
    retryable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_value(self.kind, JOB_KINDS, "job kind")
        _require_value(self.status, JOB_STATUSES, "job status")

    def to_asset_result(self) -> AssetResult:
        if self.path is None:
            raise ProviderError(
                f"provider result {self.job_id} has no output path",
                fix="Only successful provider results can be converted to legacy assets.",
            )
        return AssetResult(
            shot_id=self.shot_id,
            provider=self.provider,
            path=self.path,
            kind=legacy_asset_kind(self.kind),
            duration=self.duration,
            status="generated" if self.status == "succeeded" else "failed",
            error=self.error,
            retryable=self.retryable,
        )
