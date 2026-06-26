from __future__ import annotations

from typing import Any

from .manifest import ManifestStore
from .models import AssetResult, GenerationTask, Project
from .prompts import plan_prompt
from .providers import get_provider


def _select_shots(project: Project, only: set[str] | None = None):
    for shot in project.shots:
        if only and shot.id not in only:
            continue
        yield shot


def generate_images(
    project: Project,
    *,
    provider_name: str | None = None,
    dry_run: bool = False,
    only: set[str] | None = None,
) -> dict[str, Any] | list[AssetResult]:
    provider_name = provider_name or project.config.default_image_provider
    provider = get_provider(provider_name)
    planned: list[dict[str, str]] = []
    results: list[AssetResult] = []
    store = ManifestStore(project.config.root / "manifest.json", project_name=project.config.name)
    for shot in _select_shots(project, only):
        output = project.config.root / "generated" / "images" / f"{shot.id}.txt"
        prompt = plan_prompt(shot, provider=provider_name)
        if dry_run:
            planned.append({"shot_id": shot.id, "provider": provider_name, "output": output.as_posix()})
            continue
        result = provider.generate_image(GenerationTask(project.config, shot, prompt, output, dry_run=False))
        store.record_asset(result)
        results.append(result)
    if dry_run:
        return {"dry_run": True, "planned": planned}
    store.save()
    return results


def generate_videos(
    project: Project,
    *,
    provider_name: str | None = None,
    dry_run: bool = False,
    only: set[str] | None = None,
) -> dict[str, Any] | list[AssetResult]:
    provider_name = provider_name or project.config.default_video_provider
    provider = get_provider(provider_name)
    planned: list[dict[str, str]] = []
    results: list[AssetResult] = []
    store = ManifestStore(project.config.root / "manifest.json", project_name=project.config.name)
    for shot in _select_shots(project, only):
        output = project.config.root / "generated" / "clips" / f"{shot.id}.mp4"
        prompt = plan_prompt(shot, provider=provider_name)
        if dry_run:
            planned.append({"shot_id": shot.id, "provider": provider_name, "output": output.as_posix()})
            continue
        result = provider.generate_video(GenerationTask(project.config, shot, prompt, output, dry_run=False))
        store.record_asset(result)
        results.append(result)
    if dry_run:
        return {"dry_run": True, "planned": planned}
    store.save()
    return results
