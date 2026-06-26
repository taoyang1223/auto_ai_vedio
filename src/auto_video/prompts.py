from __future__ import annotations

from .models import ShotPlan


def _reference_lines(shot: ShotPlan) -> list[str]:
    return [
        f"- {ref.type} {ref.path}: role={ref.role}, usage={ref.usage}"
        for ref in shot.refs
    ]


def _base_lines(shot: ShotPlan) -> list[str]:
    return [
        f"Visual intent: {shot.visual_prompt}",
        f"Performance: {shot.performance}",
        f"Camera: {shot.camera_motion}",
        f"Environment motion: {shot.environment_motion}",
        f"Lighting: {shot.lighting}",
        f"Audio intent: {shot.audio_intent}",
        f"Negative: {shot.negative_prompt}",
    ]


def plan_prompt(shot: ShotPlan, *, provider: str) -> str:
    if provider == "seedance":
        parts = [
            f"Shot {shot.id}: {shot.title or shot.intent}",
            f"Duration: {shot.duration}s",
            "Director controls:",
            *_base_lines(shot),
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
            shot.visual_prompt,
            f"Performance: {shot.performance}",
            f"Camera: {shot.camera_motion}",
            f"Environment motion: {shot.environment_motion}",
            f"Lighting: {shot.lighting}",
            "continuous smooth cinematic motion, no text, no watermark",
            f"Negative: {shot.negative_prompt}",
        ]
        return "\n".join(line for line in parts if line)
    if provider == "mock":
        return f"MOCK {shot.id}: {shot.visual_prompt} ({shot.duration}s)"
    return "\n".join(line for line in _base_lines(shot) if line)
