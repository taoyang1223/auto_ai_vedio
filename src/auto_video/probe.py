from __future__ import annotations

from .models import Project


def probe_project(project: Project, *, dry_run: bool = False) -> dict:
    report = {"project": project.config.name, "dry_run": dry_run, "shots": []}
    manifest_shots = project.manifest.get("shots", {})
    for shot in project.shots:
        entry = manifest_shots.get(shot.id, {})
        manifest_duration = entry.get("duration")
        stretch_ratio = None
        if manifest_duration:
            stretch_ratio = round(float(shot.duration) / float(manifest_duration), 3)
        report["shots"].append(
            {
                "id": shot.id,
                "clip": entry.get("clip"),
                "target_duration": shot.duration,
                "manifest_duration": manifest_duration,
                "stretch_ratio": stretch_ratio,
                "status": entry.get("status", "missing"),
            }
        )
    return report
