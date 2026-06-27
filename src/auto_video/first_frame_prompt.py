from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .models import AssetRef, Project, PromptProfile, ShotPlan


PROMPT_FILE = Path("assets/first_frame_prompts.json")
DEFAULT_NEGATIVE = (
    "text, watermark, logo, low quality, blurry, motion blur, duplicated face, "
    "distorted hands, extra fingers, deformed anatomy, identity drift, style drift"
)

ROLE_LABELS = {
    "first_frame": "首帧",
    "last_frame": "尾帧",
    "style_reference": "风格参考",
    "camera_reference": "镜头参考",
    "motion_reference": "动作参考",
    "environment_reference": "场景参考",
    "voice_reference": "声音参考",
    "bgm_reference": "配乐参考",
}

USAGE_LABELS = {
    "preserve_subject": "保持主体",
    "preserve_voice": "保持声音",
    "extract_style": "提取风格",
    "extract_camera_motion": "提取镜头",
    "extract_action": "提取动作",
    "extract_audio_rhythm": "提取节奏",
    "provide_context": "提供上下文",
}


def load_saved_first_frame_prompts(root: str | Path) -> dict[str, dict[str, str]]:
    path = Path(root) / PROMPT_FILE
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError("first_frame_prompts.json must contain an object", fix="Use an object with a prompts array.")
    prompts = data.get("prompts", [])
    if not isinstance(prompts, list):
        raise ConfigError("first_frame_prompts.json prompts must be a list", fix="Store prompts as an array.")
    result: dict[str, dict[str, str]] = {}
    for raw in prompts:
        if not isinstance(raw, dict):
            continue
        shot_id = str(raw.get("shot_id") or "").strip()
        if not shot_id:
            continue
        result[shot_id] = {
            "prompt": str(raw.get("prompt") or ""),
            "negative_prompt": str(raw.get("negative_prompt") or ""),
        }
    return result


def save_first_frame_prompts(project: Project, raw_prompts: Any) -> list[dict[str, Any]]:
    prompts = raw_prompts.get("prompts") if isinstance(raw_prompts, dict) else raw_prompts
    if not isinstance(prompts, list):
        raise ConfigError("first frame prompts payload must be a list", fix="Submit a prompts array.")

    shot_ids = {shot.id for shot in project.shots}
    clean: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in prompts:
        if not isinstance(raw, dict):
            raise ConfigError("each first frame prompt must be an object", fix="Use shot_id, prompt, and negative_prompt fields.")
        shot_id = str(raw.get("shot_id") or "").strip()
        if not shot_id or shot_id not in shot_ids:
            raise ConfigError(f"unknown shot for first frame prompt: {shot_id or '<empty>'}", fix="Refresh the project and save existing shots only.")
        if shot_id in seen:
            continue
        seen.add(shot_id)
        prompt = _bounded_text(raw.get("prompt"), field_name=f"{shot_id} prompt")
        negative = _bounded_text(raw.get("negative_prompt"), field_name=f"{shot_id} negative_prompt")
        if prompt or negative:
            clean.append({"shot_id": shot_id, "prompt": prompt, "negative_prompt": negative})

    path = project.config.root / PROMPT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"prompts": clean}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return draft_first_frame_prompts(project)


def draft_first_frame_prompts(project: Project, saved_prompts: dict[str, dict[str, str]] | None = None) -> list[dict[str, Any]]:
    saved = saved_prompts if saved_prompts is not None else load_saved_first_frame_prompts(project.config.root)
    return [_prompt_payload(project, shot, saved.get(shot.id, {})) for shot in project.shots]


def _prompt_payload(project: Project, shot: ShotPlan, saved: dict[str, str]) -> dict[str, Any]:
    generated_prompt = _generated_prompt(project, shot)
    generated_negative = _combine_negative([shot.negative_prompt, project.config.prompt_profile.negative, DEFAULT_NEGATIVE])
    prompt = str(saved.get("prompt") or generated_prompt)
    negative_prompt = str(saved.get("negative_prompt") or generated_negative)
    first_frame_path = _first_frame_path(shot)
    return {
        "shot_id": shot.id,
        "title": shot.title,
        "duration": shot.duration,
        "provider": shot.provider or project.config.default_video_provider,
        "first_frame_path": first_frame_path,
        "has_first_frame": bool(first_frame_path),
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "generated_prompt": generated_prompt,
        "generated_negative_prompt": generated_negative,
        "saved": prompt != generated_prompt or negative_prompt != generated_negative,
        "refs": [_ref_payload(ref) for ref in shot.refs],
    }


def _generated_prompt(project: Project, shot: ShotPlan) -> str:
    profile = project.config.prompt_profile
    lines = [
        f"First-frame key visual for shot {shot.id}: {shot.title or shot.intent}",
        f"Format: single still image, {project.config.aspect_ratio}, {project.config.width}x{project.config.height}, image-to-video starting frame.",
        *_profile_lines(profile),
        _line("Characters in frame", ", ".join(shot.characters)),
        _line("Scene continuity key", shot.scene),
        _line("Speaker", shot.speaker),
        _line("Shot visual intent", shot.visual_prompt),
        _line("Opening performance state", shot.performance),
        _line("Camera composition", shot.camera_motion),
        _line("Environment cues", shot.environment_motion),
        _line("Lighting", shot.lighting),
        *_reference_lines(shot),
        (
            "Create a polished cinematic still frame with coherent subject identity, stable anatomy, "
            "clean composition, detailed natural materials, and enough visual direction for smooth Wan image-to-video motion."
        ),
        "No on-screen text, no watermark, no UI overlay.",
    ]
    return "\n".join(line for line in lines if line)


def _profile_lines(profile: PromptProfile) -> list[str]:
    fields = [
        ("Subject", profile.subject),
        ("Character continuity", profile.character),
        ("Setting continuity", profile.setting),
        ("Visual style", profile.visual_style),
        ("Camera style", profile.camera_style),
        ("Motion style", profile.motion_style),
        ("Lighting style", profile.lighting_style),
        ("Continuity rules", profile.continuity),
    ]
    return [_line(label, value) for label, value in fields if str(value or "").strip()]


def _reference_lines(shot: ShotPlan) -> list[str]:
    if not shot.refs:
        return []
    lines = ["Reference assets:"]
    for ref in shot.refs:
        lines.append(
            f"- {ROLE_LABELS.get(ref.role, ref.role)} / {USAGE_LABELS.get(ref.usage, ref.usage)}: {ref.path}"
        )
    return lines


def _ref_payload(ref: AssetRef) -> dict[str, Any]:
    return {
        **asdict(ref),
        "role_label": ROLE_LABELS.get(ref.role, ref.role),
        "usage_label": USAGE_LABELS.get(ref.usage, ref.usage),
    }


def _first_frame_path(shot: ShotPlan) -> str:
    for ref in shot.refs:
        if ref.type == "image" and ref.role == "first_frame":
            return ref.path
    return ""


def _line(label: str, value: Any) -> str:
    text = str(value or "").strip()
    return f"{label}: {text}" if text else ""


def _bounded_text(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if len(text) > 20000:
        raise ConfigError(f"{field_name} is too long", fix="Keep each prompt under 20,000 characters.")
    return text


def _combine_negative(values: list[str]) -> str:
    seen: set[str] = set()
    terms: list[str] = []
    for value in values:
        for part in str(value or "").split(","):
            term = part.strip()
            key = term.casefold()
            if not term or key in seen:
                continue
            seen.add(key)
            terms.append(term)
    return ", ".join(terms)
