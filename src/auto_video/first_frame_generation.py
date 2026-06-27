from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import struct
import zlib
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .pipeline import submit_jobs
from .project import load_project, resolve_project_path
from .models import Project


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def generate_first_frames(
    project: Project,
    *,
    provider_name: str | None = None,
    only: set[str] | None = None,
    failed_only: bool = False,
    skip_succeeded: bool = False,
) -> dict[str, Any]:
    results = submit_jobs(
        project,
        kind="image",
        provider_name=provider_name,
        only=only,
        failed_only=failed_only,
        skip_succeeded=skip_succeeded,
    )
    refreshed = load_project(project.config.root)
    requested = only or {result.shot_id for result in results}
    return {
        "count": len(results),
        "submitted": [_result_summary(result, refreshed.config.root) for result in results],
        "first_frames": promote_generated_images_to_first_frames(refreshed, only=requested),
    }


def promote_generated_images_to_first_frames(project: Project, *, only: set[str] | None = None) -> dict[str, Any]:
    manifest_shots = project.manifest.get("shots", {}) if isinstance(project.manifest, dict) else {}
    promoted: list[dict[str, Any]] = []
    missing: list[str] = []
    failed: list[dict[str, str]] = []

    for shot in project.shots:
        if only and shot.id not in only:
            continue
        record = manifest_shots.get(shot.id) if isinstance(manifest_shots, dict) else None
        image_path = str(record.get("image") or "") if isinstance(record, dict) else ""
        if not image_path:
            missing.append(shot.id)
            continue
        source = resolve_project_path(project.config.root, image_path)
        if not source.exists() or not source.is_file():
            failed.append({"shot_id": shot.id, "error": f"generated image not found: {image_path}"})
            continue
        target_relative = _first_frame_relative_path(shot.id, source)
        target = resolve_project_path(project.config.root, target_relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        normalized = False
        if source.suffix.lower() in IMAGE_SUFFIXES:
            if source.resolve() != target.resolve():
                normalized = _normalize_image_for_project(
                    source,
                    target,
                    width=max(64, int(project.config.width)),
                    height=max(64, int(project.config.height)),
                )
                if not normalized:
                    shutil.copy2(source, target)
        else:
            body = _placeholder_png(
                max(64, int(project.config.width)),
                max(64, int(project.config.height)),
                seed=f"{shot.id}:{source.read_bytes().hex()[:96]}",
            )
            target.write_bytes(body)
            normalized = True
        _set_first_frame_ref(project.config.root, shot.id, target_relative)
        promoted.append(
            {
                "shot_id": shot.id,
                "source": image_path,
                "path": target_relative,
                "bytes": target.stat().st_size,
                "normalized": normalized,
            }
        )

    return {"count": len(promoted), "promoted": promoted, "missing": missing, "failed": failed}


def _set_first_frame_ref(root: Path, shot_id: str, relative_path: str) -> None:
    shots_path = root / "shots.json"
    data = json.loads(shots_path.read_text(encoding="utf-8"))
    shots = data.get("shots")
    if not isinstance(shots, list):
        raise ConfigError("shots.json must contain shots", fix="Restore a valid shots.json.")
    found = False
    for shot in shots:
        if str(shot.get("id")) != shot_id:
            continue
        refs = shot.setdefault("refs", [])
        if not isinstance(refs, list):
            refs = []
            shot["refs"] = refs
        for ref in refs:
            if isinstance(ref, dict) and ref.get("type") == "image" and ref.get("role") == "first_frame":
                ref["path"] = relative_path
                ref["usage"] = ref.get("usage") or "preserve_subject"
                found = True
                break
        if not found:
            refs.insert(
                0,
                {
                    "path": relative_path,
                    "type": "image",
                    "role": "first_frame",
                    "usage": "preserve_subject",
                },
            )
            found = True
        break
    if not found:
        raise ConfigError(f"shot {shot_id} not found", fix="Refresh the project and choose an existing shot.")
    shots_path.write_text(json.dumps({"shots": shots}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _first_frame_relative_path(shot_id: str, source: Path) -> str:
    suffix = source.suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        suffix = ".png"
    return f"assets/refs/{_safe_name(shot_id)}_first_frame{suffix}"


def _safe_name(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value).strip("_")
    return safe or "shot"


def _normalize_image_for_project(source: Path, target: Path, *, width: int, height: int) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    tmp = target.with_name(f".{target.stem}.normalizing{target.suffix or '.png'}")
    tmp.unlink(missing_ok=True)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        source.as_posix(),
        "-vf",
        f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1",
        "-frames:v",
        "1",
        tmp.as_posix(),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(target)
    return True


def _placeholder_png(width: int, height: int, *, seed: str) -> bytes:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    start = (digest[0], digest[1], digest[2])
    end = (digest[3], digest[4], digest[5])
    rows = bytearray()
    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = tuple(int(start[i] * (1 - ratio) + end[i] * ratio) for i in range(3))
        rows.append(0)
        for _x in range(width):
            rows.extend(color)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(bytes(rows), level=9))
        + _png_chunk(b"IEND", b"")
    )


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def _result_summary(result: Any, root: Path) -> dict[str, Any]:
    path = result.path
    if path is not None:
        try:
            path_text = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            path_text = path.as_posix()
    else:
        path_text = None
    return {
        "job_id": result.job_id,
        "shot_id": result.shot_id,
        "kind": result.kind,
        "provider": result.provider,
        "status": result.status,
        "path": path_text,
        "error": result.error,
        "retryable": result.retryable,
        "metadata": result.metadata,
    }
