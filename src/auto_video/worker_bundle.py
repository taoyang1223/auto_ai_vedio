from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .errors import AssetError, ConfigError
from .job_builder import build_jobs
from .jobs import GenerationJob, ProviderResult, utc_now_iso
from .models import Project
from .project import resolve_project_path

BUNDLE_SCHEMA_VERSION = "0.1"


def safe_bundle_filename(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    return f"{safe}.json"


def safe_ref_filename(value: str) -> str:
    path = Path(value)
    suffix = path.suffix
    base = value[: -len(suffix)] if suffix else value
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in base).strip("_")
    return f"{safe}{suffix}" if suffix else safe


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _ensure_empty_bundle(path: Path, *, force: bool) -> None:
    if path.exists() and any(path.iterdir()):
        if not force:
            raise ConfigError(
                f"bundle directory {path} already exists and is not empty",
                fix="Choose an empty --out directory or pass --force.",
            )
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _ensure_bundle_target(project_root: Path, bundle: Path) -> None:
    if bundle.resolve() == project_root.resolve():
        raise ConfigError(
            "bundle output cannot be the project root",
            fix="Choose a separate --out directory so --force cannot remove project files.",
        )


def _copy_project_snapshot(project: Project, bundle: Path) -> None:
    for name in ("project.yaml", "shots.json"):
        source = project.config.root / name
        if source.exists():
            shutil.copy2(source, bundle / name)


def _copy_reference_assets(project: Project, bundle: Path, jobs: list[GenerationJob]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for job in jobs:
        for ref in job.refs:
            ref_record = {
                "job_id": job.id,
                "source": ref.path,
                "role": ref.role,
                "usage": ref.usage,
            }
            source = resolve_project_path(project.config.root, ref.path)
            if source.exists():
                target = bundle / "refs" / job.shot_id / safe_ref_filename(ref.path)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                ref_record["bundle_path"] = _relative(target, bundle)
                ref_record["missing"] = False
            else:
                ref_record["missing"] = True
            refs.append(ref_record)
    return refs


def export_worker_bundle(
    project: Project,
    bundle: Path,
    *,
    kind: str,
    provider_name: str | None = None,
    only: set[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    _ensure_bundle_target(project.config.root, bundle)
    _ensure_empty_bundle(bundle, force=force)
    (bundle / "jobs").mkdir(parents=True, exist_ok=True)
    (bundle / "refs").mkdir(parents=True, exist_ok=True)
    (bundle / "outputs").mkdir(parents=True, exist_ok=True)
    (bundle / "logs").mkdir(parents=True, exist_ok=True)
    _copy_project_snapshot(project, bundle)

    jobs = build_jobs(project, kind=kind, provider_name=provider_name, only=only)
    job_paths: list[str] = []
    for job in jobs:
        job_path = bundle / "jobs" / safe_bundle_filename(job.id)
        job_path.write_text(json.dumps(job.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        job_paths.append(_relative(job_path, bundle))

    index = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "project": project.config.name,
        "created_at": utc_now_iso(),
        "source_root": project.config.root.as_posix(),
        "jobs": job_paths,
        "refs": _copy_reference_assets(project, bundle, jobs),
        "results": [],
    }
    (bundle / "bundle.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return index


def _resolve_inside(root: Path, value: str) -> Path:
    if Path(value).is_absolute():
        raise AssetError(f"path {value!r} must be relative", fix="Use a relative path inside the bundle.")
    candidate = (root / value).resolve()
    root = root.resolve()
    if candidate != root and root not in candidate.parents:
        raise AssetError(f"path {value!r} escapes bundle root", fix="Remove '..' path traversal.")
    return candidate


def load_bundle_index(bundle: Path) -> dict[str, Any]:
    path = bundle / "bundle.json"
    if not path.exists():
        raise ConfigError(f"missing {path}", fix="Run worker export before worker run.")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        raise ConfigError(
            f"unsupported bundle schema {data.get('schema_version')!r}",
            fix=f"Use schema version {BUNDLE_SCHEMA_VERSION}.",
        )
    return data


def load_bundle_jobs(bundle: Path) -> list[GenerationJob]:
    index = load_bundle_index(bundle)
    jobs: list[GenerationJob] = []
    for item in index.get("jobs", []):
        path = _resolve_inside(bundle, str(item))
        jobs.append(GenerationJob.from_dict(json.loads(path.read_text(encoding="utf-8"))))
    return jobs


def provider_result_to_dict(result: ProviderResult, bundle: Path) -> dict[str, Any]:
    path = None
    if result.path is not None:
        path = _relative(result.path, bundle)
    return {
        "job_id": result.job_id,
        "shot_id": result.shot_id,
        "kind": result.kind,
        "provider": result.provider,
        "status": result.status,
        "path": path,
        "duration": result.duration,
        "provider_job_id": result.provider_job_id,
        "error": result.error,
        "retryable": result.retryable,
        "metadata": result.metadata,
    }
