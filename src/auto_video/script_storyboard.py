from __future__ import annotations

import re
from typing import Any

from .errors import ConfigError
from .models import Project


MAX_SCRIPT_CHARS = 8000
MIN_SHOT_COUNT = 1
MAX_SHOT_COUNT = 12

BASE_NEGATIVE = "text, watermark, logo, bad hands, extra fingers, distorted body, low quality, blurry"

ROLE_PRESETS = (
    {
        "title": "开场建立",
        "intent": "建立主体、场景和情绪基调",
        "shot": "cinematic establishing shot",
        "camera": "slow dolly in with stable framing",
        "environment": "subtle ambient movement, gentle light changes",
        "performance": "main subject enters the moment with controlled natural movement",
        "lighting": "soft key light with clean practical highlights",
        "audio": "quiet opening texture with a restrained cinematic pulse",
    },
    {
        "title": "问题出现",
        "intent": "呈现目标、矛盾或变化的起点",
        "shot": "medium cinematic shot",
        "camera": "measured push in, slight parallax",
        "environment": "background details respond subtly to the action",
        "performance": "subject reacts with clear but natural expression",
        "lighting": "balanced contrast, focused subject highlight",
        "audio": "soft rise in rhythm and room texture",
    },
    {
        "title": "过程推进",
        "intent": "展示行动过程和关键细节",
        "shot": "dynamic process shot",
        "camera": "sideways tracking shot with smooth motion",
        "environment": "objects shift gently, reflections travel across surfaces",
        "performance": "hands and body movement stay precise and believable",
        "lighting": "mixed practical light with cinematic depth",
        "audio": "clean production texture with subtle mechanical accents",
    },
    {
        "title": "关键转折",
        "intent": "表现变化、突破或情绪转折",
        "shot": "cinematic reveal shot",
        "camera": "slow crane up and controlled push forward",
        "environment": "light and surrounding elements intensify coherently",
        "performance": "subject pauses, then completes the decisive action",
        "lighting": "stronger rim light, clean highlight separation",
        "audio": "rising cue leading into a polished reveal",
    },
    {
        "title": "结果揭示",
        "intent": "交代结果并形成完整收束",
        "shot": "hero final shot",
        "camera": "slow push forward, stable hero composition",
        "environment": "final screen glow and calm atmospheric motion",
        "performance": "subject steps back and observes the finished result",
        "lighting": "premium cinematic finish with soft backlight",
        "audio": "resolved musical hit with clean room ambience",
    },
)


def draft_storyboard_from_script(project: Project, payload: dict[str, Any]) -> dict[str, Any]:
    script = _normalize_script(str(payload.get("script") or ""))
    if not script:
        raise ConfigError("脚本不能为空", fix="请输入中文创意、故事梗概或口播文案。")
    if len(script) > MAX_SCRIPT_CHARS:
        raise ConfigError("脚本过长", fix=f"请控制在 {MAX_SCRIPT_CHARS} 个字符以内。")

    shot_count = _bounded_int(payload.get("shot_count"), default=max(len(project.shots), 3))
    duration = _bounded_float(payload.get("duration"), default=4.0)
    provider = str(payload.get("provider") or project.config.default_video_provider).strip()
    segments = _segments_for_count(script, shot_count)
    profile = project.config.prompt_profile

    shots = []
    for index, segment in enumerate(segments):
        preset = _role_preset(index, shot_count)
        shots.append(
            {
                "id": f"S{index + 1:02d}",
                "title": _shot_title(preset["title"], segment),
                "duration": duration,
                "intent": f"{preset['intent']}：{segment}",
                "provider": provider,
                "visual_prompt": _visual_prompt(segment, preset, project, profile),
                "camera_motion": _join_control(preset["camera"], profile.camera_style),
                "environment_motion": _join_control(preset["environment"], profile.motion_style),
                "performance": preset["performance"],
                "lighting": _join_control(preset["lighting"], profile.lighting_style),
                "audio_intent": preset["audio"],
                "subtitle": _subtitle(segment),
                "negative_prompt": BASE_NEGATIVE,
                "refs": [],
            }
        )

    return {
        "shots": shots,
        "source_segments": segments,
        "meta": {
            "shot_count": shot_count,
            "duration": duration,
            "provider": provider,
        },
    }


def _normalize_script(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u3000", " ")).strip()


def _bounded_int(value: Any, *, default: int) -> int:
    try:
        result = int(float(value))
    except (TypeError, ValueError):
        result = default
    if result < MIN_SHOT_COUNT or result > MAX_SHOT_COUNT:
        raise ConfigError("分镜数量超出范围", fix=f"请填写 {MIN_SHOT_COUNT} 到 {MAX_SHOT_COUNT} 之间的数量。")
    return result


def _bounded_float(value: Any, *, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    if result <= 0 or result > 15:
        raise ConfigError("单镜时长超出范围", fix="请填写 0 到 15 秒之间的时长。")
    return round(result, 2)


def _segments_for_count(script: str, count: int) -> list[str]:
    parts = _split_script(script)
    if len(parts) >= count:
        return _merge_segments(parts, count)
    return _extend_segments(parts or [script], script, count)


def _split_script(script: str) -> list[str]:
    primary = [
        _clean_segment(part)
        for part in re.split(r"[\n。！？!?；;]+", script)
        if _clean_segment(part)
    ]
    if len(primary) >= 2:
        return primary
    secondary = [
        _clean_segment(part)
        for part in re.split(r"[，,、：:]+", script)
        if _clean_segment(part)
    ]
    return secondary or primary


def _merge_segments(parts: list[str], count: int) -> list[str]:
    groups: list[list[str]] = [[] for _ in range(count)]
    for index, part in enumerate(parts):
        group_index = min(count - 1, int(index * count / len(parts)))
        groups[group_index].append(part)
    return [_truncate("，".join(group), 120) for group in groups]


def _extend_segments(parts: list[str], script: str, count: int) -> list[str]:
    result: list[str] = []
    for index in range(count):
        preset = _role_preset(index, count)
        base = parts[min(index, len(parts) - 1)] if parts else script
        if index >= len(parts):
            base = f"{preset['title']}：{script}"
        result.append(_truncate(_clean_segment(base), 120))
    return result


def _role_preset(index: int, count: int) -> dict[str, str]:
    if count == 1:
        return ROLE_PRESETS[-1]
    if index == 0:
        return ROLE_PRESETS[0]
    if index == count - 1:
        return ROLE_PRESETS[-1]
    progress = index / max(count - 1, 1)
    if progress < 0.35:
        return ROLE_PRESETS[1]
    if progress < 0.7:
        return ROLE_PRESETS[2]
    return ROLE_PRESETS[3]


def _visual_prompt(segment: str, preset: dict[str, str], project: Project, profile: Any) -> str:
    subject = profile.subject or "核心人物、产品或事件"
    setting = profile.setting or "主要故事场景"
    style = profile.visual_style or "realistic cinematic commercial film, refined detail"
    return (
        f"{preset['shot']}, {subject}, {setting}, story beat: {segment}, "
        f"{style}, {project.config.aspect_ratio} composition, coherent motion, high detail"
    )


def _join_control(primary: str, extra: str) -> str:
    extra = extra.strip()
    if not extra:
        return primary
    return f"{primary}, {extra}"


def _shot_title(prefix: str, segment: str) -> str:
    return f"{prefix} · {_truncate(segment, 14)}"


def _subtitle(segment: str) -> str:
    return _truncate(segment, 36)


def _clean_segment(value: str) -> str:
    return value.strip(" \t\r\n，,。.!！?？；;：:、")


def _truncate(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"
