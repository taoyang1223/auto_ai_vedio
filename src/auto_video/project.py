from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .errors import AssetError, ConfigError
from .models import (
    AssetRef,
    Project,
    ProjectConfig,
    RenderConfig,
    RenderText,
    RenderTransition,
    ShotPlan,
)


def resolve_project_path(root: Path, value: str) -> Path:
    root = root.resolve()
    candidate = (root / value).resolve()
    if candidate != root and root not in candidate.parents:
        raise AssetError(
            f"path {value!r} escapes project root {root}",
            fix="Use a relative path inside the project directory.",
        )
    return candidate


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"missing {path.name}", fix=f"Create {path.name} in the project root.")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} must contain a mapping", fix="Use key/value YAML fields.")
    return data


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"missing {path.name}", fix=f"Create {path.name} in the project root.")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} must contain a JSON object", fix="Use an object with a shots array.")
    return data


def _render_config(data: dict[str, Any]) -> RenderConfig:
    render = data.get("render") or {}
    transition_data = render.get("transition") or {}
    brand_data = render.get("brand")
    cta_data = render.get("cta")
    return RenderConfig(
        transition=RenderTransition(
            type=str(transition_data.get("type", "fade")),
            duration=float(transition_data.get("duration", 0.6)),
        ),
        bgm=render.get("bgm"),
        bgm_volume=float(render.get("bgm_volume", 0.2)),
        subtitle_style=str(render.get("subtitle_style", "default")),
        brand=RenderText(text=str(brand_data["text"]), at=float(brand_data["at"])) if brand_data else None,
        cta=RenderText(text=str(cta_data["text"]), at=float(cta_data["at"])) if cta_data else None,
    )


def _project_config(root: Path, data: dict[str, Any]) -> ProjectConfig:
    name = data.get("name")
    if not name:
        raise ConfigError("project.yaml missing name", fix="Set a non-empty name field.")
    return ProjectConfig(
        name=str(name),
        root=root,
        aspect_ratio=str(data.get("aspect_ratio", "9:16")),
        width=int(data.get("width", 1080)),
        height=int(data.get("height", 1920)),
        fps=int(data.get("fps", 30)),
        default_video_provider=str(data.get("default_video_provider", "mock")),
        default_image_provider=str(data.get("default_image_provider", "mock")),
        default_audio_provider=str(data.get("default_audio_provider", "mock")),
        render=_render_config(data),
    )


def _shot_plan(raw: dict[str, Any]) -> ShotPlan:
    refs = tuple(AssetRef(**ref) for ref in raw.get("refs", []))
    return ShotPlan(
        id=str(raw["id"]),
        title=str(raw.get("title", "")),
        duration=float(raw["duration"]),
        intent=str(raw.get("intent", "")),
        provider=raw.get("provider"),
        visual_prompt=str(raw.get("visual_prompt", "")),
        camera_motion=str(raw.get("camera_motion", "")),
        environment_motion=str(raw.get("environment_motion", "")),
        performance=str(raw.get("performance", "")),
        lighting=str(raw.get("lighting", "")),
        audio_intent=str(raw.get("audio_intent", "")),
        subtitle=str(raw.get("subtitle", "")),
        negative_prompt=str(raw.get("negative_prompt", "")),
        refs=refs,
    )


def load_project(root: str | Path) -> Project:
    root = Path(root).resolve()
    config_data = _read_yaml(root / "project.yaml")
    shots_data = _read_json(root / "shots.json")
    shots_raw = shots_data.get("shots")
    if not isinstance(shots_raw, list) or not shots_raw:
        raise ConfigError("shots.json must contain a non-empty shots array", fix="Add at least one shot.")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    return Project(
        config=_project_config(root, config_data),
        shots=tuple(_shot_plan(raw) for raw in shots_raw),
        manifest=manifest,
    )
