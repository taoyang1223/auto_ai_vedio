from __future__ import annotations

from typing import Any

from .job_builder import build_jobs
from .job_selection import select_jobs
from .job_store import JobStore
from .jobs import ProviderResult
from .models import AssetResult, Project
from .providers import get_provider


def _plan_payload(jobs) -> dict[str, Any]:
    return {"dry_run": True, "planned": [job.to_dict() for job in jobs]}


def plan_jobs(
    project: Project,
    *,
    kind: str,
    provider_name: str | None = None,
    only: set[str] | None = None,
    failed_only: bool = False,
    skip_succeeded: bool = False,
) -> dict[str, Any]:
    jobs = build_jobs(project, kind=kind, provider_name=provider_name, only=only)
    jobs = select_jobs(jobs, project.manifest, failed_only=failed_only, skip_succeeded=skip_succeeded)
    return _plan_payload(jobs)


def submit_jobs(
    project: Project,
    *,
    kind: str,
    provider_name: str | None = None,
    only: set[str] | None = None,
    failed_only: bool = False,
    skip_succeeded: bool = False,
) -> list[ProviderResult]:
    jobs = build_jobs(project, kind=kind, provider_name=provider_name, only=only)
    jobs = select_jobs(jobs, project.manifest, failed_only=failed_only, skip_succeeded=skip_succeeded)
    store = JobStore(project.config.root / "manifest.json", project_name=project.config.name)
    results: list[ProviderResult] = []
    for job in jobs:
        provider = get_provider(job.provider, project.config.providers.get(job.provider))
        store.record_job(job)
        result = provider.execute_job(job, project.config.root)
        store.record_result(result)
        results.append(result)
    store.save()
    return results


def _asset_results(results: list[ProviderResult]) -> list[AssetResult]:
    return [result.to_asset_result() for result in results]


def generate_images(
    project: Project,
    *,
    provider_name: str | None = None,
    dry_run: bool = False,
    only: set[str] | None = None,
    failed_only: bool = False,
    skip_succeeded: bool = False,
) -> dict[str, Any] | list[AssetResult]:
    if dry_run:
        return plan_jobs(
            project,
            kind="image",
            provider_name=provider_name,
            only=only,
            failed_only=failed_only,
            skip_succeeded=skip_succeeded,
        )
    return _asset_results(
        submit_jobs(
            project,
            kind="image",
            provider_name=provider_name,
            only=only,
            failed_only=failed_only,
            skip_succeeded=skip_succeeded,
        )
    )


def generate_videos(
    project: Project,
    *,
    provider_name: str | None = None,
    dry_run: bool = False,
    only: set[str] | None = None,
    failed_only: bool = False,
    skip_succeeded: bool = False,
) -> dict[str, Any] | list[AssetResult]:
    if dry_run:
        return plan_jobs(
            project,
            kind="video",
            provider_name=provider_name,
            only=only,
            failed_only=failed_only,
            skip_succeeded=skip_succeeded,
        )
    return _asset_results(
        submit_jobs(
            project,
            kind="video",
            provider_name=provider_name,
            only=only,
            failed_only=failed_only,
            skip_succeeded=skip_succeeded,
        )
    )


def generate_audio(
    project: Project,
    *,
    provider_name: str | None = None,
    dry_run: bool = False,
    only: set[str] | None = None,
    failed_only: bool = False,
    skip_succeeded: bool = False,
) -> dict[str, Any] | list[AssetResult]:
    if dry_run:
        return plan_jobs(
            project,
            kind="audio",
            provider_name=provider_name,
            only=only,
            failed_only=failed_only,
            skip_succeeded=skip_succeeded,
        )
    return _asset_results(
        submit_jobs(
            project,
            kind="audio",
            provider_name=provider_name,
            only=only,
            failed_only=failed_only,
            skip_succeeded=skip_succeeded,
        )
    )
