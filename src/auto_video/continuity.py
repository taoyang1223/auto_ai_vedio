from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
import subprocess

from .errors import ConfigError, ProviderError
from .manifest import ManifestStore
from .models import Project
from .project import resolve_project_path


@dataclass(frozen=True)
class TailFrameTask:
    shot_id: str
    next_shot_id: str
    clip: Path
    output: Path


class TailFrameExtractor(Protocol):
    def extract(self, clip: Path, output: Path) -> None:
        """Extract one tail frame from clip into output."""


class FFmpegTailFrameExtractor:
    def extract(self, clip: Path, output: Path) -> None:
        command = (
            "ffmpeg",
            "-y",
            "-sseof",
            "-0.1",
            "-i",
            clip.as_posix(),
            "-frames:v",
            "1",
            output.as_posix(),
        )
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise ConfigError("missing command 'ffmpeg'", fix="Install ffmpeg to extract continuity tail frames.") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise ProviderError(
                f"ffmpeg failed while extracting tail frame for {clip.as_posix()}",
                fix=stderr or "Check that the generated clip is readable.",
            ) from exc


def build_tail_frame_tasks(project: Project) -> list[TailFrameTask]:
    tasks: list[TailFrameTask] = []
    shots = project.manifest.get("shots", {}) if isinstance(project.manifest, dict) else {}
    for current, nxt in zip(project.shots, project.shots[1:]):
        shot_record = shots.get(current.id) if isinstance(shots, dict) else None
        if not isinstance(shot_record, dict) or not (shot_record.get("lipsync_clip") or shot_record.get("clip")):
            continue
        clip = resolve_project_path(project.config.root, str(shot_record.get("lipsync_clip") or shot_record["clip"]))
        output = project.config.root / "assets" / "continuity" / f"{current.id}_tail.png"
        tasks.append(TailFrameTask(shot_id=current.id, next_shot_id=nxt.id, clip=clip, output=output))
    return tasks


def extract_tail_frames(
    project: Project,
    *,
    extractor: TailFrameExtractor | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    tasks = build_tail_frame_tasks(project)
    extracted: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    planned: list[dict[str, str]] = []
    store = ManifestStore(project.config.root / "manifest.json", project_name=project.config.name)
    frame_extractor = extractor or FFmpegTailFrameExtractor()

    for task in tasks:
        item = _task_dict(project, task)
        if not task.clip.exists():
            skipped.append({**item, "reason": "missing_clip"})
            continue
        if dry_run:
            planned.append(item)
            continue
        if task.output.exists() and not force:
            _record_continuity_ref(store, project, task)
            skipped.append({**item, "reason": "exists"})
            continue
        task.output.parent.mkdir(parents=True, exist_ok=True)
        frame_extractor.extract(task.clip, task.output)
        _record_continuity_ref(store, project, task)
        extracted.append(item)

    if not dry_run:
        store.save()
    return {
        "dry_run": dry_run,
        "planned": planned,
        "extracted": extracted,
        "skipped": skipped,
    }


def continuity_refs_for_shot(project: Project, shot_id: str) -> list[dict[str, Any]]:
    shots = project.manifest.get("shots", {}) if isinstance(project.manifest, dict) else {}
    shot = shots.get(shot_id) if isinstance(shots, dict) else None
    if not isinstance(shot, dict):
        return []
    refs = shot.get("continuity_refs", [])
    if not isinstance(refs, list):
        return []
    return [dict(ref) for ref in refs if isinstance(ref, dict)]


def _record_continuity_ref(store: ManifestStore, project: Project, task: TailFrameTask) -> None:
    current = store.data["shots"].setdefault(task.shot_id, {})
    current["tail_frame"] = store._relative(task.output)
    nxt = store.data["shots"].setdefault(task.next_shot_id, {})
    refs = nxt.setdefault("continuity_refs", [])
    if not isinstance(refs, list):
        refs = []
        nxt["continuity_refs"] = refs
    record = {
        "path": store._relative(task.output),
        "type": "image",
        "role": "first_frame",
        "usage": "preserve_subject",
        "source_shot_id": task.shot_id,
    }
    refs[:] = [ref for ref in refs if not (isinstance(ref, dict) and ref.get("source_shot_id") == task.shot_id)]
    refs.append(record)


def _task_dict(project: Project, task: TailFrameTask) -> dict[str, str]:
    return {
        "shot_id": task.shot_id,
        "next_shot_id": task.next_shot_id,
        "clip": _relative(project.config.root, task.clip),
        "output": _relative(project.config.root, task.output),
    }


def _relative(root: Path, value: Path) -> str:
    try:
        return value.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return value.as_posix()
