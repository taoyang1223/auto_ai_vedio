from __future__ import annotations

import subprocess
import shutil
from pathlib import Path
from typing import Any, Protocol

from .errors import RenderError
from .manifest import ManifestStore
from .models import Project
from .project import resolve_project_path
from .jobs import utc_now_iso


class RenderRunner(Protocol):
    def run(self, command: tuple[str, ...]) -> None:
        """Run a render command or raise a user-facing error."""


class SubprocessRenderRunner:
    def run(self, command: tuple[str, ...]) -> None:
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise RenderError("missing command 'ffmpeg'", fix="Install ffmpeg to assemble the final video.") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise RenderError("ffmpeg failed while assembling final video", fix=stderr or "Check clip codecs.") from exc


def build_render_plan(project: Project) -> dict:
    shots = []
    manifest_shots = project.manifest.get("shots", {})
    for shot in project.shots:
        entry = manifest_shots.get(shot.id, {})
        clip = entry.get("clip")
        if not clip:
            raise RenderError(
                f"shot {shot.id} has no generated clip in manifest",
                fix="Run auto-video generate before assemble, or use assemble --dry-run before requiring media.",
            )
        clip_path = resolve_project_path(project.config.root, str(clip))
        shots.append(
            {
                "id": shot.id,
                "clip": str(clip),
                "clip_path": clip_path.as_posix(),
                "duration": shot.duration,
                "subtitle": shot.subtitle,
                "exists": clip_path.exists(),
                "bytes": clip_path.stat().st_size if clip_path.exists() else 0,
            }
        )
    output = "renders/final.mp4"
    concat_file = "renders/final.concat.txt"
    output_path = (project.config.root / output).as_posix()
    concat_path = (project.config.root / concat_file).as_posix()
    ffmpeg = ["ffmpeg", "-y"]
    ffmpeg.extend(["-f", "concat", "-safe", "0", "-i", concat_path, "-c", "copy", output_path])
    return {
        "output": output,
        "output_path": output_path,
        "concat_file": concat_file,
        "concat_path": concat_path,
        "width": project.config.width,
        "height": project.config.height,
        "fps": project.config.fps,
        "transition": {
            "type": project.config.render.transition.type,
            "duration": project.config.render.transition.duration,
        },
        "shots": shots,
        "ffmpeg": ffmpeg,
    }


def assemble_project(
    project: Project,
    *,
    dry_run: bool = False,
    runner: RenderRunner | None = None,
) -> dict[str, Any]:
    plan = build_render_plan(project)
    checks = _quality_checks(plan)
    result = {"dry_run": dry_run, **plan, "checks": checks}
    if dry_run:
        return result
    failed = [check for check in checks if check["status"] == "failed"]
    if failed:
        first = failed[0]
        raise RenderError(first["message"], fix=first.get("fix", "Fix render input checks and retry."))

    root = project.config.root
    output = resolve_project_path(root, str(plan["output"]))
    concat_file = resolve_project_path(root, str(plan["concat_file"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    concat_file.parent.mkdir(parents=True, exist_ok=True)
    archived = _archive_existing_render(root, output)
    _write_concat_file(project.config.root, plan, concat_file)
    command = tuple(str(part) for part in plan["ffmpeg"])
    (runner or SubprocessRenderRunner()).run(command)
    if not output.exists() or output.stat().st_size == 0:
        raise RenderError(
            f"render output {plan['output']} was not created",
            fix="Check ffmpeg output and clip compatibility.",
        )
    _record_render(project, output, command, archived=archived)
    return {**result, "status": "succeeded", "bytes": output.stat().st_size, "archived": archived}


def _quality_checks(plan: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for shot in plan["shots"]:
        if not shot["exists"]:
            checks.append(
                {
                    "name": "clip_exists",
                    "shot_id": shot["id"],
                    "status": "failed",
                    "message": f"clip {shot['clip']} is missing",
                    "fix": "Regenerate the shot before assembling.",
                }
            )
            continue
        if int(shot["bytes"]) <= 0:
            checks.append(
                {
                    "name": "clip_nonempty",
                    "shot_id": shot["id"],
                    "status": "failed",
                    "message": f"clip {shot['clip']} is empty",
                    "fix": "Regenerate the shot before assembling.",
                }
            )
            continue
        checks.append(
            {
                "name": "clip_ready",
                "shot_id": shot["id"],
                "status": "ok",
                "message": f"clip {shot['clip']} is ready",
                "bytes": shot["bytes"],
            }
        )
    return checks


def _write_concat_file(project_root: Path, plan: dict[str, Any], concat_file: Path) -> None:
    lines = []
    for shot in plan["shots"]:
        path = resolve_project_path(project_root, str(shot["clip"]))
        lines.append(f"file '{path.as_posix()}'")
    concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _archive_existing_render(project_root: Path, output: Path) -> dict[str, Any] | None:
    if not output.exists() or output.stat().st_size <= 0:
        return None
    stamp = utc_now_iso().replace(":", "").replace("-", "").replace("Z", "Z")
    archive = project_root / "renders" / "versions" / f"{output.stem}_{stamp}{output.suffix}"
    archive.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output, archive)
    return {
        "path": _relative(project_root, archive),
        "archived_at": utc_now_iso(),
        "bytes": archive.stat().st_size,
    }


def _record_render(project: Project, output: Path, command: tuple[str, ...], *, archived: dict[str, Any] | None = None) -> None:
    store = ManifestStore(project.config.root / "manifest.json", project_name=project.config.name)
    previous = store.data["renders"].get("final")
    versions = []
    if isinstance(previous, dict) and isinstance(previous.get("versions"), list):
        versions = list(previous["versions"])
    if archived:
        versions.append(archived)
    store.data["renders"]["final"] = {
        "status": "generated",
        "path": store._relative(output),
        "command": list(command),
    }
    if versions:
        store.data["renders"]["final"]["versions"] = versions
    store.save()


def _relative(root: Path, value: Path) -> str:
    try:
        return value.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return value.as_posix()
