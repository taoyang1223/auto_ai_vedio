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
    PromptProfile,
    ProviderConfig,
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


def _provider_configs(data: dict[str, Any]) -> dict[str, ProviderConfig]:
    providers = data.get("providers") or {}
    if not isinstance(providers, dict):
        raise ConfigError("providers must be a mapping", fix="Use provider names as keys under providers.")
    result: dict[str, ProviderConfig] = {}
    for name, raw in providers.items():
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ConfigError(f"provider {name} config must be a mapping", fix="Use key/value provider settings.")
        known = {"mode", "endpoint_env", "token_env", "timeout_seconds", "max_attempts"}
        options = {key: value for key, value in raw.items() if key not in known}
        result[str(name)] = ProviderConfig(
            mode=str(raw.get("mode", "local")),
            endpoint_env=raw.get("endpoint_env"),
            token_env=raw.get("token_env"),
            timeout_seconds=int(raw.get("timeout_seconds", 900)),
            max_attempts=int(raw.get("max_attempts", 1)),
            options=options,
        )
    result.setdefault("mock", ProviderConfig(mode="local", timeout_seconds=30, max_attempts=1))
    return result


def _remote_profiles(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    profiles = data.get("remote_profiles") or {}
    if not isinstance(profiles, dict):
        raise ConfigError("remote_profiles must be a mapping", fix="Use profile names as keys under remote_profiles.")
    result: dict[str, dict[str, Any]] = {}
    for name, raw in profiles.items():
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ConfigError(f"remote profile {name} must be a mapping", fix="Use key/value profile settings.")
        result[str(name)] = dict(raw)
    return result


def _comfyui_workflows(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    workflows = data.get("comfyui_workflows") or {}
    if not isinstance(workflows, dict):
        raise ConfigError("comfyui_workflows must be a mapping", fix="Use workflow profile names as keys.")
    result: dict[str, dict[str, Any]] = {}
    for name, raw in workflows.items():
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ConfigError(f"ComfyUI workflow {name} must be a mapping", fix="Use key/value workflow settings.")
        result[str(name)] = dict(raw)
    return result


def _prompt_profile(data: dict[str, Any]) -> PromptProfile:
    raw = data.get("prompt_profile") or {}
    if not isinstance(raw, dict):
        raise ConfigError("prompt_profile must be a mapping", fix="Use key/value prompt continuity fields.")
    return PromptProfile(
        subject=str(raw.get("subject", "")),
        character=str(raw.get("character", "")),
        setting=str(raw.get("setting", "")),
        visual_style=str(raw.get("visual_style", "")),
        camera_style=str(raw.get("camera_style", "")),
        motion_style=str(raw.get("motion_style", "")),
        lighting_style=str(raw.get("lighting_style", "")),
        continuity=str(raw.get("continuity", "")),
        negative=str(raw.get("negative", "")),
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
        providers=_provider_configs(data),
        remote_profiles=_remote_profiles(data),
        comfyui_workflows=_comfyui_workflows(data),
        prompt_profile=_prompt_profile(data),
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
