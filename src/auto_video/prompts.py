from __future__ import annotations

from .models import PromptProfile, ShotPlan


def _reference_lines(shot: ShotPlan) -> list[str]:
    return [
        f"- {ref.type} {ref.path}: role={ref.role}, usage={ref.usage}"
        for ref in shot.refs
    ]


def _combine_negative(shot: ShotPlan, profile: PromptProfile | None) -> str:
    parts = [shot.negative_prompt]
    if profile:
        parts.append(profile.negative)
    seen: set[str] = set()
    result: list[str] = []
    for value in parts:
        for part in str(value or "").split(","):
            item = part.strip()
            key = item.casefold()
            if not item or key in seen:
                continue
            seen.add(key)
            result.append(item)
    return ", ".join(result)


def _profile_lines(profile: PromptProfile | None) -> list[str]:
    if not profile:
        return []
    return [
        f"Subject: {profile.subject}",
        f"Character continuity: {profile.character}",
        f"Setting continuity: {profile.setting}",
        f"Visual style: {profile.visual_style}",
        f"Camera style: {profile.camera_style}",
        f"Motion style: {profile.motion_style}",
        f"Lighting style: {profile.lighting_style}",
        f"Continuity rules: {profile.continuity}",
    ]


def _base_lines(shot: ShotPlan, profile: PromptProfile | None = None) -> list[str]:
    return [
        *_profile_lines(profile),
        f"Visual intent: {shot.visual_prompt}",
        f"Performance: {shot.performance}",
        f"Camera: {shot.camera_motion}",
        f"Environment motion: {shot.environment_motion}",
        f"Lighting: {shot.lighting}",
        f"Audio intent: {shot.audio_intent}",
        f"Negative: {_combine_negative(shot, profile)}",
    ]


def plan_prompt(shot: ShotPlan, *, provider: str, profile: PromptProfile | None = None) -> str:
    if provider == "seedance":
        parts = [
            f"Shot {shot.id}: {shot.title or shot.intent}",
            f"Duration: {shot.duration}s",
            "Director controls:",
            *_base_lines(shot, profile),
            "References:",
            *_reference_lines(shot),
            (
                "Generate a coherent 4-15 second multimodal video shot with clear "
                "subject motion, camera motion, environment motion, and audio-video timing."
            ),
        ]
        return "\n".join(line for line in parts if line)
    if provider == "wan":
        parts = [
            *_profile_lines(profile),
            shot.visual_prompt,
            f"Performance: {shot.performance}",
            f"Camera: {shot.camera_motion}",
            f"Environment motion: {shot.environment_motion}",
            f"Lighting: {shot.lighting}",
            "continuous smooth cinematic motion, no text, no watermark",
            f"Negative: {_combine_negative(shot, profile)}",
        ]
        return "\n".join(line for line in parts if line)
    if provider == "mock":
        return f"MOCK {shot.id}: {shot.visual_prompt} ({shot.duration}s)"
    return "\n".join(line for line in _base_lines(shot, profile) if line)
