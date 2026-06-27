from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import ProbeError
from .media_quality import (
    MediaProbeRunner,
    SubprocessMediaProbeRunner,
    build_blackdetect_check,
    build_media_checks,
    inspect_media,
    status_from_checks,
    summarize_checks,
)
from .models import Project
from .project import resolve_project_path


def probe_project(
    project: Project,
    *,
    dry_run: bool = False,
    runner: MediaProbeRunner | None = None,
    ffprobe: str = "ffprobe",
    ffmpeg: str = "ffmpeg",
    min_duration_ratio: float = 0.8,
    blackdetect: bool = False,
    max_black_ratio: float = 0.98,
) -> dict[str, Any]:
    report = {"project": project.config.name, "dry_run": dry_run, "shots": []}
    manifest_shots = project.manifest.get("shots", {})
    media_runner = runner or SubprocessMediaProbeRunner(ffprobe=ffprobe, ffmpeg=ffmpeg)
    for shot in project.shots:
        entry = manifest_shots.get(shot.id, {})
        manifest_duration = entry.get("duration")
        stretch_ratio = None
        if manifest_duration:
            stretch_ratio = round(float(shot.duration) / float(manifest_duration), 3)
        shot_report = {
            "id": shot.id,
            "clip": entry.get("clip"),
            "target_duration": shot.duration,
            "manifest_duration": manifest_duration,
            "stretch_ratio": stretch_ratio,
            "status": entry.get("status", "missing"),
        }
        quality = _probe_clip(
            project,
            shot_id=shot.id,
            clip=entry.get("clip"),
            target_duration=shot.duration,
            dry_run=dry_run,
            runner=media_runner,
            min_duration_ratio=min_duration_ratio,
            blackdetect=blackdetect,
            max_black_ratio=max_black_ratio,
        )
        shot_report.update(quality)
        report["shots"].append(shot_report)
    report["summary"] = summarize_checks(report["shots"])
    return report


def _probe_clip(
    project: Project,
    *,
    shot_id: str,
    clip: Any,
    target_duration: float,
    dry_run: bool,
    runner: MediaProbeRunner,
    min_duration_ratio: float,
    blackdetect: bool,
    max_black_ratio: float,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    media: dict[str, Any] | None = None
    if not clip:
        checks.append(
            {
                "name": "clip_manifest",
                "shot_id": shot_id,
                "status": "failed",
                "message": "manifest has no generated clip",
                "fix": "Run auto-video generate or auto-video remote run before probing.",
            }
        )
        return {"quality_status": status_from_checks(checks), "checks": checks, "media": media}

    clip_path = resolve_project_path(project.config.root, str(clip))
    checks.extend(_file_checks(shot_id=shot_id, clip=str(clip), clip_path=clip_path))
    if any(check["status"] == "failed" for check in checks):
        return {"quality_status": status_from_checks(checks), "checks": checks, "media": media}
    if dry_run:
        checks.append(
            {
                "name": "media_probe",
                "shot_id": shot_id,
                "status": "skipped",
                "message": "media probing skipped in dry-run mode",
            }
        )
        return {"quality_status": status_from_checks(checks), "checks": checks, "media": media}

    try:
        media = inspect_media(runner.probe(clip_path))
        checks.extend(
            build_media_checks(
                media,
                shot_id=shot_id,
                expected_width=project.config.width,
                expected_height=project.config.height,
                expected_fps=project.config.fps,
                target_duration=target_duration,
                min_duration_ratio=min_duration_ratio,
            )
        )
        if blackdetect:
            checks.append(
                build_blackdetect_check(
                    runner.blackdetect(clip_path),
                    shot_id=shot_id,
                    duration=media.get("duration"),
                    max_black_ratio=max_black_ratio,
                )
            )
    except ProbeError as exc:
        checks.append(
            {
                "name": "media_probe",
                "shot_id": shot_id,
                "status": "failed",
                "message": exc.message,
                "fix": exc.fix or "Regenerate the clip or install ffprobe/ffmpeg.",
            }
        )
    return {"quality_status": status_from_checks(checks), "checks": checks, "media": media}


def _file_checks(*, shot_id: str, clip: str, clip_path: Path) -> list[dict[str, Any]]:
    if not clip_path.exists():
        return [
            {
                "name": "clip_exists",
                "shot_id": shot_id,
                "status": "failed",
                "message": f"clip {clip} is missing",
                "fix": "Regenerate the shot before probing.",
            }
        ]
    if clip_path.stat().st_size <= 0:
        return [
            {
                "name": "clip_nonempty",
                "shot_id": shot_id,
                "status": "failed",
                "message": f"clip {clip} is empty",
                "fix": "Regenerate the shot before probing.",
            }
        ]
    return [
        {
            "name": "clip_ready",
            "shot_id": shot_id,
            "status": "ok",
            "message": f"clip {clip} is ready",
            "bytes": clip_path.stat().st_size,
        }
    ]
