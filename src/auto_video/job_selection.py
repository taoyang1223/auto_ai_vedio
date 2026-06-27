from __future__ import annotations

from typing import Any

from .errors import ConfigError
from .jobs import GenerationJob

FAILED_JOB_STATUSES = {"failed", "retryable_failed"}


def select_jobs(
    jobs: list[GenerationJob],
    manifest: dict[str, Any],
    *,
    failed_only: bool = False,
    skip_succeeded: bool = False,
) -> list[GenerationJob]:
    if failed_only and skip_succeeded:
        raise ConfigError(
            "failed-only and skip-succeeded cannot be used together",
            fix="Choose one job selection mode.",
        )
    if failed_only:
        return [job for job in jobs if _job_status(job, manifest) in FAILED_JOB_STATUSES]
    if skip_succeeded:
        return [job for job in jobs if _job_status(job, manifest) != "succeeded" or _job_needs_refresh(job, manifest)]
    return jobs


def _job_status(job: GenerationJob, manifest: dict[str, Any]) -> str:
    jobs = manifest.get("jobs", {}) if isinstance(manifest, dict) else {}
    record = jobs.get(job.id) if isinstance(jobs, dict) else None
    if isinstance(record, dict) and record.get("status"):
        return str(record["status"])

    shots = manifest.get("shots", {}) if isinstance(manifest, dict) else {}
    shot = shots.get(job.shot_id) if isinstance(shots, dict) else None
    if not isinstance(shot, dict):
        return ""
    if shot.get("status") == "failed":
        return "failed"
    if shot.get("status") == "generated" and _shot_has_kind_output(job.kind, shot):
        return "succeeded"
    return ""


def _shot_has_kind_output(kind: str, shot: dict[str, Any]) -> bool:
    if kind == "video":
        return bool(shot.get("clip"))
    if kind == "image":
        return bool(shot.get("image"))
    if kind == "audio":
        return bool(shot.get("audio"))
    if kind == "lipsync":
        return bool(shot.get("lipsync_clip"))
    return False


def _job_needs_refresh(job: GenerationJob, manifest: dict[str, Any]) -> bool:
    previous_hash = _previous_input_hash(job, manifest)
    current_hash = str(job.metadata.get("input_hash") or "")
    if previous_hash and current_hash and previous_hash != current_hash:
        return True
    if not job.output_exists:
        return True
    if job.output_updated_at is None:
        return False
    for ref in job.refs:
        if ref.exists and ref.updated_at is not None and ref.updated_at > job.output_updated_at:
            return True
    return False


def _previous_input_hash(job: GenerationJob, manifest: dict[str, Any]) -> str:
    jobs = manifest.get("jobs", {}) if isinstance(manifest, dict) else {}
    record = jobs.get(job.id) if isinstance(jobs, dict) else None
    if not isinstance(record, dict):
        return ""
    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        return ""
    return str(metadata.get("input_hash") or "")
