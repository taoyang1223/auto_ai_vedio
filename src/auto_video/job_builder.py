from __future__ import annotations

import hashlib
import json

from .jobs import (
    GenerationJob,
    ProviderControls,
    ProviderReference,
    make_job_id,
    relative_output_path,
    utc_now_iso,
)
from .continuity import continuity_refs_for_shot
from .first_frame_prompt import draft_first_frame_prompts
from .models import Project, ShotPlan
from .project import resolve_project_path
from .prompts import plan_prompt


def _default_provider(project: Project, kind: str) -> str:
    if kind == "image":
        return project.config.default_image_provider
    if kind == "audio":
        return project.config.default_audio_provider
    return project.config.default_video_provider


def _select_shots(project: Project, only: set[str] | None = None):
    for shot in project.shots:
        if only and shot.id not in only:
            continue
        yield shot


def _provider_refs(project: Project, shot: ShotPlan) -> tuple[ProviderReference, ...]:
    refs: list[ProviderReference] = []
    for ref in continuity_refs_for_shot(project, shot.id):
        path = str(ref.get("path", ""))
        if not path:
            continue
        source = resolve_project_path(project.config.root, path)
        refs.append(
            ProviderReference(
                path=path,
                type=str(ref.get("type", "image")),
                role=str(ref.get("role", "first_frame")),
                usage=str(ref.get("usage", "preserve_subject")),
                exists=source.exists(),
                updated_at=_mtime(source),
            )
        )
    for ref in shot.refs:
        source = resolve_project_path(project.config.root, ref.path)
        refs.append(
            ProviderReference(
                path=ref.path,
                type=ref.type,
                role=ref.role,
                usage=ref.usage,
                exists=source.exists(),
                updated_at=_mtime(source),
            )
        )
    return tuple(refs)


def _mtime(path) -> float | None:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return None


def _controls(project: Project, shot: ShotPlan) -> ProviderControls:
    return ProviderControls(
        visual_prompt=shot.visual_prompt,
        camera_motion=shot.camera_motion,
        environment_motion=shot.environment_motion,
        performance=shot.performance,
        lighting=shot.lighting,
        audio_intent=shot.audio_intent,
        subtitle=shot.subtitle,
        negative_prompt=shot.negative_prompt,
        aspect_ratio=project.config.aspect_ratio,
        width=project.config.width,
        height=project.config.height,
        fps=project.config.fps,
        characters=shot.characters,
        scene=shot.scene,
        speaker=shot.speaker,
        voice=shot.voice,
        wardrobe=shot.wardrobe,
    )


def build_jobs(
    project: Project,
    *,
    kind: str,
    provider_name: str | None = None,
    only: set[str] | None = None,
) -> list[GenerationJob]:
    jobs: list[GenerationJob] = []
    image_prompts = _first_frame_prompt_map(project) if kind == "image" else {}
    for shot in _select_shots(project, only):
        provider = provider_name or (shot.provider if kind == "video" else None) or _default_provider(project, kind)
        prompt = image_prompts.get(shot.id, {}).get("prompt") or plan_prompt(
            shot,
            provider=provider,
            profile=project.config.prompt_profile,
        )
        negative_prompt = image_prompts.get(shot.id, {}).get("negative_prompt") or shot.negative_prompt
        now = utc_now_iso()
        output_path = relative_output_path(shot.id, kind)
        output = resolve_project_path(project.config.root, output_path)
        refs = _provider_refs(project, shot)
        controls = _controls(project, shot)
        metadata = _job_metadata(
            kind=kind,
            provider=provider,
            prompt=prompt,
            negative_prompt=negative_prompt,
            duration=shot.duration if kind in {"video", "audio"} else None,
            refs=refs,
            controls=controls,
            speaker=shot.speaker,
            voice=shot.voice,
            scene=shot.scene,
            characters=shot.characters,
            wardrobe=shot.wardrobe,
        )
        jobs.append(
            GenerationJob(
                id=make_job_id(project.config.name, shot.id, kind, provider),
                project_name=project.config.name,
                shot_id=shot.id,
                kind=kind,
                provider=provider,
                prompt=prompt,
                negative_prompt=negative_prompt,
                duration=shot.duration if kind in {"video", "audio"} else None,
                output_path=output_path,
                output_exists=output.exists(),
                output_updated_at=_mtime(output),
                refs=refs,
                controls=controls,
                created_at=now,
                updated_at=now,
                metadata=metadata,
            )
        )
    return jobs


def _job_metadata(
    *,
    kind: str,
    provider: str,
    prompt: str,
    negative_prompt: str,
    duration: float | None,
    refs: tuple[ProviderReference, ...],
    controls: ProviderControls,
    speaker: str = "",
    voice: str = "",
    scene: str = "",
    characters: tuple[str, ...] = (),
    wardrobe: str = "",
) -> dict[str, str]:
    payload = {
        "kind": kind,
        "provider": provider,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "duration": duration,
        "controls": controls.to_dict(),
        "speaker": speaker,
        "voice": voice,
        "scene": scene,
        "characters": list(characters),
        "wardrobe": wardrobe,
        "refs": [
            {
                "path": ref.path,
                "type": ref.type,
                "role": ref.role,
                "usage": ref.usage,
            }
            for ref in refs
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    metadata = {"input_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest()}
    for key, value in {
        "speaker": speaker,
        "voice": voice,
        "scene": scene,
        "wardrobe": wardrobe,
    }.items():
        if value:
            metadata[key] = value
    if characters:
        metadata["characters"] = ",".join(characters)
    return metadata


def _first_frame_prompt_map(project: Project) -> dict[str, dict[str, str]]:
    return {
        str(item["shot_id"]): {
            "prompt": str(item.get("prompt") or ""),
            "negative_prompt": str(item.get("negative_prompt") or ""),
        }
        for item in draft_first_frame_prompts(project)
    }
