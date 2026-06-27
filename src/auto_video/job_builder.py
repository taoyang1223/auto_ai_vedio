from __future__ import annotations

from .jobs import (
    GenerationJob,
    ProviderControls,
    ProviderReference,
    make_job_id,
    relative_output_path,
    utc_now_iso,
)
from .continuity import continuity_refs_for_shot
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
        refs.append(
            ProviderReference(
                path=path,
                type=str(ref.get("type", "image")),
                role=str(ref.get("role", "first_frame")),
                usage=str(ref.get("usage", "preserve_subject")),
                exists=resolve_project_path(project.config.root, path).exists(),
            )
        )
    for ref in shot.refs:
        refs.append(
            ProviderReference(
                path=ref.path,
                type=ref.type,
                role=ref.role,
                usage=ref.usage,
                exists=resolve_project_path(project.config.root, ref.path).exists(),
            )
        )
    return tuple(refs)


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
    )


def build_jobs(
    project: Project,
    *,
    kind: str,
    provider_name: str | None = None,
    only: set[str] | None = None,
) -> list[GenerationJob]:
    jobs: list[GenerationJob] = []
    for shot in _select_shots(project, only):
        provider = provider_name or shot.provider or _default_provider(project, kind)
        now = utc_now_iso()
        jobs.append(
            GenerationJob(
                id=make_job_id(project.config.name, shot.id, kind, provider),
                project_name=project.config.name,
                shot_id=shot.id,
                kind=kind,
                provider=provider,
                prompt=plan_prompt(shot, provider=provider),
                negative_prompt=shot.negative_prompt,
                duration=shot.duration if kind in {"video", "audio"} else None,
                output_path=relative_output_path(shot.id, kind),
                refs=_provider_refs(project, shot),
                controls=_controls(project, shot),
                created_at=now,
                updated_at=now,
            )
        )
    return jobs
