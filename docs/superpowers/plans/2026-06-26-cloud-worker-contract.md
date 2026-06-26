# Cloud Worker Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a local, deterministic worker bundle contract for exporting generation jobs, running them outside the source project, and importing results back into the project manifest.

**Architecture:** Add a `worker_bundle` module for bundle export/import and path safety, a `worker_runner` module for executing bundle jobs through the existing provider gateway, and CLI commands under `auto-video worker`. The implementation reuses Phase 2 `GenerationJob`, `ProviderResult`, `JobStore`, `build_jobs()`, and `MockProvider.execute_job()` so future cloud transports only need to move bundles and invoke the worker command.

**Tech Stack:** Python 3.12, dataclasses, pathlib, JSON/YAML, shutil, argparse, pytest, existing `auto_video` package.

---

## File Map

- Create `src/auto_video/worker_bundle.py`: bundle path helpers, sanitized filenames, export bundle, load bundle, import results, result serialization, path safety.
- Create `src/auto_video/worker_runner.py`: execute bundle jobs through provider gateway and write `result.json` plus `logs/worker.log`.
- Modify `src/auto_video/cli.py`: add `worker export`, `worker run`, and `worker import`.
- Modify `README.md`: document local worker workflow.
- Test with `tests/test_worker_bundle.py` and `tests/test_worker_cli.py`.

## Task 1: Worker Bundle Export

**Files:**
- Create: `src/auto_video/worker_bundle.py`
- Test: `tests/test_worker_bundle.py`

- [ ] **Step 1: Write failing bundle export tests**

Create `tests/test_worker_bundle.py`:

```python
import json

import pytest

from auto_video.errors import ConfigError
from auto_video.project import load_project
from auto_video.worker_bundle import export_worker_bundle, safe_bundle_filename


def test_safe_bundle_filename_replaces_unsafe_job_id_chars():
    assert safe_bundle_filename("demo_ad:S01:video:mock") == "demo_ad_S01_video_mock.json"


def test_export_worker_bundle_creates_layout_and_copies_refs(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    bundle = tmp_path / "bundle"

    summary = export_worker_bundle(project, bundle, kind="video", provider_name="mock")

    assert summary["project"] == "demo_ad"
    assert summary["jobs"] == ["jobs/demo_ad_S01_video_mock.json"]
    assert (bundle / "bundle.json").exists()
    assert (bundle / "project.yaml").exists()
    assert (bundle / "shots.json").exists()
    assert (bundle / "jobs" / "demo_ad_S01_video_mock.json").exists()
    assert (bundle / "refs" / "S01" / "assets_refs_S01.txt").read_text(encoding="utf-8") == "mock ref"
    assert (bundle / "outputs").is_dir()
    assert (bundle / "logs").is_dir()
    assert not (demo_project_files / "manifest.json").exists()

    index = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    assert index["refs"][0]["source"] == "assets/refs/S01.txt"
    assert index["refs"][0]["bundle_path"] == "refs/S01/assets_refs_S01.txt"


def test_export_rejects_existing_non_empty_bundle_without_force(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "keep.txt").write_text("do not remove", encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        export_worker_bundle(project, bundle, kind="video", provider_name="mock")

    assert "already exists" in str(exc.value)
    assert (bundle / "keep.txt").exists()


def test_export_force_replaces_existing_bundle(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "old.txt").write_text("old", encoding="utf-8")

    export_worker_bundle(project, bundle, kind="video", provider_name="mock", force=True)

    assert not (bundle / "old.txt").exists()
    assert (bundle / "bundle.json").exists()


def test_export_rejects_project_root_as_bundle_even_with_force(demo_project_files):
    project = load_project(demo_project_files)

    with pytest.raises(ConfigError) as exc:
        export_worker_bundle(project, demo_project_files, kind="video", provider_name="mock", force=True)

    assert "project root" in str(exc.value)
    assert (demo_project_files / "project.yaml").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_worker_bundle.py -v
```

Expected: FAIL because `auto_video.worker_bundle` does not exist.

- [ ] **Step 3: Implement worker bundle export**

Create `src/auto_video/worker_bundle.py`:

```python
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
```

- [ ] **Step 4: Run bundle export tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_worker_bundle.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/auto_video/worker_bundle.py tests/test_worker_bundle.py
git commit -m "feat: export worker bundles"
```

## Task 2: Worker Bundle Run

**Files:**
- Modify: `src/auto_video/worker_bundle.py`
- Create: `src/auto_video/worker_runner.py`
- Test: `tests/test_worker_runner.py`

- [ ] **Step 1: Write failing worker run tests**

Create `tests/test_worker_runner.py`:

```python
import json
import shutil

from auto_video.project import load_project
from auto_video.worker_bundle import export_worker_bundle
from auto_video.worker_runner import run_worker_bundle


def test_run_worker_bundle_writes_outputs_result_and_log(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    bundle = tmp_path / "bundle"
    export_worker_bundle(project, bundle, kind="video", provider_name="mock")

    result = run_worker_bundle(bundle)

    output = bundle / "outputs" / "generated" / "clips" / "S01.mp4"
    result_json = json.loads((bundle / "result.json").read_text(encoding="utf-8"))
    assert result["results"][0]["job_id"] == "demo_ad:S01:video:mock"
    assert output.read_text(encoding="utf-8").startswith("mock video")
    assert result_json["results"][0]["path"] == "outputs/generated/clips/S01.mp4"
    assert (bundle / "logs" / "worker.log").read_text(encoding="utf-8").startswith("started")


def test_run_worker_bundle_does_not_need_source_project(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    bundle = tmp_path / "bundle"
    export_worker_bundle(project, bundle, kind="video", provider_name="mock")
    shutil.rmtree(demo_project_files)

    result = run_worker_bundle(bundle)

    assert result["results"][0]["status"] == "succeeded"
    assert (bundle / "outputs" / "generated" / "clips" / "S01.mp4").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_worker_runner.py -v
```

Expected: FAIL because `auto_video.worker_runner` does not exist.

- [ ] **Step 3: Add bundle loading and result conversion helpers**

Append to `src/auto_video/worker_bundle.py`:

```python
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
```

- [ ] **Step 4: Implement worker runner**

Create `src/auto_video/worker_runner.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .jobs import ProviderResult
from .providers import get_provider
from .worker_bundle import BUNDLE_SCHEMA_VERSION, load_bundle_index, load_bundle_jobs, provider_result_to_dict


def run_worker_bundle(bundle: Path) -> dict[str, Any]:
    index = load_bundle_index(bundle)
    (bundle / "outputs").mkdir(parents=True, exist_ok=True)
    (bundle / "logs").mkdir(parents=True, exist_ok=True)
    log_path = bundle / "logs" / "worker.log"
    log_lines = ["started worker bundle run"]
    results: list[ProviderResult] = []
    for job in load_bundle_jobs(bundle):
        provider = get_provider(job.provider)
        worker_job = job.__class__(
            **{
                **job.to_dict(),
                "output_path": f"outputs/{job.output_path}",
                "refs": job.refs,
                "controls": job.controls,
            }
        )
        try:
            result = provider.execute_job(worker_job, bundle)
            result = ProviderResult(
                job_id=job.id,
                shot_id=job.shot_id,
                kind=job.kind,
                provider=job.provider,
                status=result.status,
                path=result.path,
                duration=result.duration,
                provider_job_id=result.provider_job_id,
                error=result.error,
                retryable=result.retryable,
                metadata={**result.metadata, "worker": "local"},
            )
        except Exception as exc:
            result = ProviderResult(
                job_id=job.id,
                shot_id=job.shot_id,
                kind=job.kind,
                provider=job.provider,
                status="retryable_failed",
                error=str(exc),
                retryable=True,
                metadata={"worker": "local"},
            )
        results.append(result)
        log_lines.append(f"{job.id} {result.status}")
    payload: dict[str, Any] = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "project": index.get("project"),
        "results": [provider_result_to_dict(result, bundle) for result in results],
    }
    (bundle / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    return payload
```

- [ ] **Step 5: Run worker runner tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_worker_runner.py -v
```

Expected: PASS.

- [ ] **Step 6: Run bundle export tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_worker_bundle.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/auto_video/worker_bundle.py src/auto_video/worker_runner.py tests/test_worker_runner.py
git commit -m "feat: run worker bundles locally"
```

## Task 3: Worker Result Import

**Files:**
- Modify: `src/auto_video/worker_bundle.py`
- Test: `tests/test_worker_import.py`

- [ ] **Step 1: Write failing import tests**

Create `tests/test_worker_import.py`:

```python
import json

from auto_video.project import load_project
from auto_video.worker_bundle import export_worker_bundle, import_worker_results
from auto_video.worker_runner import run_worker_bundle


def test_import_worker_results_copies_output_and_updates_manifest(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    bundle = tmp_path / "bundle"
    export_worker_bundle(project, bundle, kind="video", provider_name="mock")
    run_worker_bundle(bundle)

    summary = import_worker_results(demo_project_files, bundle)

    manifest = json.loads((demo_project_files / "manifest.json").read_text(encoding="utf-8"))
    assert summary["imported"] == ["demo_ad:S01:video:mock"]
    assert (demo_project_files / "generated" / "clips" / "S01.mp4").exists()
    assert manifest["jobs"]["demo_ad:S01:video:mock"]["status"] == "succeeded"
    assert manifest["shots"]["S01"]["clip"] == "generated/clips/S01.mp4"


def test_import_worker_failure_records_job_without_legacy_clip(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    bundle = tmp_path / "bundle"
    export_worker_bundle(project, bundle, kind="video", provider_name="mock")
    (bundle / "result.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "project": "demo_ad",
                "results": [
                    {
                        "job_id": "demo_ad:S01:video:mock",
                        "shot_id": "S01",
                        "kind": "video",
                        "provider": "mock",
                        "status": "retryable_failed",
                        "path": None,
                        "duration": None,
                        "provider_job_id": None,
                        "error": "NoGPU",
                        "retryable": True,
                        "metadata": {"worker": "local"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    summary = import_worker_results(demo_project_files, bundle)

    manifest = json.loads((demo_project_files / "manifest.json").read_text(encoding="utf-8"))
    assert summary["failed"] == ["demo_ad:S01:video:mock"]
    assert manifest["jobs"]["demo_ad:S01:video:mock"]["status"] == "retryable_failed"
    assert manifest["jobs"]["demo_ad:S01:video:mock"]["error"] == "NoGPU"
    assert "clip" not in manifest["shots"]["S01"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_worker_import.py -v
```

Expected: FAIL because `import_worker_results` does not exist.

- [ ] **Step 3: Add import helpers**

Append to `src/auto_video/worker_bundle.py`:

```python
def _result_from_dict(data: dict[str, Any], bundle: Path) -> ProviderResult:
    path_value = data.get("path")
    path = _resolve_inside(bundle, str(path_value)) if path_value else None
    return ProviderResult(
        job_id=str(data["job_id"]),
        shot_id=str(data["shot_id"]),
        kind=str(data["kind"]),
        provider=str(data["provider"]),
        status=str(data["status"]),
        path=path,
        duration=float(data["duration"]) if data.get("duration") is not None else None,
        provider_job_id=data.get("provider_job_id"),
        error=data.get("error"),
        retryable=bool(data.get("retryable", False)),
        metadata=dict(data.get("metadata", {})),
    )


def _project_output_path(project_root: Path, bundle: Path, result: ProviderResult) -> Path | None:
    if result.path is None:
        return None
    relative_to_bundle = result.path.resolve().relative_to(bundle.resolve())
    if not relative_to_bundle.parts or relative_to_bundle.parts[0] != "outputs":
        raise AssetError(f"result path {relative_to_bundle} is not inside bundle outputs", fix="Use worker result paths under outputs/.")
    project_relative = Path(*relative_to_bundle.parts[1:])
    return resolve_project_path(project_root, project_relative.as_posix())


def import_worker_results(project_root: Path, bundle: Path) -> dict[str, list[str]]:
    result_path = bundle / "result.json"
    if not result_path.exists():
        raise ConfigError(f"missing {result_path}", fix="Run worker run before worker import.")
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    project = None
    from .project import load_project
    from .job_store import JobStore

    project = load_project(project_root)
    store = JobStore(project.config.root / "manifest.json", project_name=project.config.name)
    imported: list[str] = []
    failed: list[str] = []
    for item in payload.get("results", []):
        result = _result_from_dict(item, bundle)
        if result.status == "succeeded" and result.path is not None:
            destination = _project_output_path(project.config.root, bundle, result)
            assert destination is not None
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(result.path, destination)
            result = ProviderResult(
                job_id=result.job_id,
                shot_id=result.shot_id,
                kind=result.kind,
                provider=result.provider,
                status=result.status,
                path=destination,
                duration=result.duration,
                provider_job_id=result.provider_job_id,
                error=result.error,
                retryable=result.retryable,
                metadata=result.metadata,
            )
            imported.append(result.job_id)
        else:
            failed.append(result.job_id)
        store.record_result(result)
    store.save()
    return {"imported": imported, "failed": failed}
```

- [ ] **Step 4: Run import tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_worker_import.py -v
```

Expected: PASS.

- [ ] **Step 5: Run worker runner tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_worker_runner.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/auto_video/worker_bundle.py tests/test_worker_import.py
git commit -m "feat: import worker bundle results"
```

## Task 4: Worker CLI Commands

**Files:**
- Modify: `src/auto_video/cli.py`
- Test: `tests/test_worker_cli.py`

- [ ] **Step 1: Write failing worker CLI tests**

Create `tests/test_worker_cli.py`:

```python
import json
from pathlib import Path

from auto_video.cli import main


def test_worker_cli_export_run_import(tmp_path: Path, capsys):
    project = tmp_path / "demo"
    bundle = tmp_path / "bundle"
    assert main(["init", str(project)]) == 0

    assert main(["worker", "export", str(project), "--provider", "mock", "--kind", "video", "--out", str(bundle)]) == 0
    assert (bundle / "bundle.json").exists()
    assert not (project / "manifest.json").exists()

    assert main(["worker", "run", str(bundle)]) == 0
    assert (bundle / "result.json").exists()

    assert main(["worker", "import", str(project), str(bundle)]) == 0
    assert (project / "generated" / "clips" / "S01.mp4").exists()
    capsys.readouterr()

    assert main(["jobs", "status", str(project)]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["by_status"]["succeeded"] == 1


def test_worker_cli_export_existing_bundle_requires_force(tmp_path: Path):
    project = tmp_path / "demo"
    bundle = tmp_path / "bundle"
    assert main(["init", str(project)]) == 0
    assert main(["worker", "export", str(project), "--provider", "mock", "--kind", "video", "--out", str(bundle)]) == 0

    assert main(["worker", "export", str(project), "--provider", "mock", "--kind", "video", "--out", str(bundle)]) == 1
    assert main(["worker", "export", str(project), "--provider", "mock", "--kind", "video", "--out", str(bundle), "--force"]) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_worker_cli.py -v
```

Expected: FAIL because `worker` CLI group is not implemented.

- [ ] **Step 3: Add CLI imports**

Modify `src/auto_video/cli.py` imports:

```python
from .worker_bundle import export_worker_bundle, import_worker_results
from .worker_runner import run_worker_bundle
```

- [ ] **Step 4: Add worker parser**

In `build_parser()` before `providers = sub.add_parser("providers")`, add:

```python
    worker = sub.add_parser("worker")
    worker_sub = worker.add_subparsers(dest="worker_command")

    worker_export = worker_sub.add_parser("export")
    worker_export.add_argument("project")
    worker_export.add_argument("--provider")
    worker_export.add_argument("--kind", choices=["image", "video", "audio"], default="video")
    worker_export.add_argument("--only")
    worker_export.add_argument("--out", required=True)
    worker_export.add_argument("--force", action="store_true")

    worker_run = worker_sub.add_parser("run")
    worker_run.add_argument("bundle")

    worker_import = worker_sub.add_parser("import")
    worker_import.add_argument("project")
    worker_import.add_argument("bundle")
```

- [ ] **Step 5: Add worker command handling**

In `main()`, before the existing `providers` block, add:

```python
        if args.command == "worker" and args.worker_command == "export":
            result = export_worker_bundle(
                load_project(args.project),
                Path(args.out),
                kind=args.kind,
                provider_name=args.provider,
                only=_csv(args.only),
                force=args.force,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "worker" and args.worker_command == "run":
            result = run_worker_bundle(Path(args.bundle))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "worker" and args.worker_command == "import":
            result = import_worker_results(Path(args.project), Path(args.bundle))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
```

- [ ] **Step 6: Run worker CLI tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_worker_cli.py -v
```

Expected: PASS.

- [ ] **Step 7: Run existing CLI tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli.py tests/test_cli_jobs.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/auto_video/cli.py tests/test_worker_cli.py
git commit -m "feat: add worker bundle CLI commands"
```

## Task 5: README And Example Worker Workflow

**Files:**
- Modify: `README.md`
- Test: `tests/test_worker_cli.py`

- [ ] **Step 1: Add checked-in example worker export test**

Append to `tests/test_worker_cli.py`:

```python
def test_checked_in_example_worker_export(tmp_path: Path):
    bundle = tmp_path / "example-bundle"

    assert main(["worker", "export", "examples/demo_project", "--provider", "mock", "--kind", "video", "--out", str(bundle)]) == 0

    assert (bundle / "bundle.json").exists()
    assert not (Path("examples/demo_project") / "manifest.json").exists()
```

- [ ] **Step 2: Run checked-in example worker test**

Run:

```bash
.venv/bin/python -m pytest tests/test_worker_cli.py::test_checked_in_example_worker_export -v
```

Expected: PASS.

- [ ] **Step 3: Update README**

Modify the MVP workflow block in `README.md` to include:

```bash
.venv/bin/python -m auto_video worker export demo_project --provider mock --kind video --out /tmp/av-bundle --force
.venv/bin/python -m auto_video worker run /tmp/av-bundle
.venv/bin/python -m auto_video worker import demo_project /tmp/av-bundle
```

Add this section after "Provider Job Runtime":

```markdown
## Cloud Worker Contract

Phase 3 adds a portable worker bundle workflow:

    .venv/bin/python -m auto_video worker export demo_project --provider mock --kind video --out /tmp/av-bundle --force
    .venv/bin/python -m auto_video worker run /tmp/av-bundle
    .venv/bin/python -m auto_video worker import demo_project /tmp/av-bundle

The first worker is local and deterministic. It proves the export/run/import contract without needing a GPU, cloud account, object storage, FFmpeg, or API key. A future cloud transport only needs to move the bundle to a rented GPU machine, run the same worker command, and bring the result bundle back.
```

- [ ] **Step 4: Run worker CLI tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_worker_cli.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md tests/test_worker_cli.py
git commit -m "docs: document cloud worker workflow"
```

## Task 6: Full Verification And Remote Sync

**Files:**
- No source changes expected unless verification exposes an issue.

- [ ] **Step 1: Run full test suite**

Run:

```bash
.venv/bin/python -m pytest -v
```

Expected: all tests PASS.

- [ ] **Step 2: Run CLI smoke for worker workflow**

Run:

```bash
set -euo pipefail
TMPDIR="$(mktemp -d)"
.venv/bin/python -m auto_video init "$TMPDIR/demo"
.venv/bin/python -m auto_video validate "$TMPDIR/demo"
.venv/bin/python -m auto_video worker export "$TMPDIR/demo" --provider mock --kind video --out "$TMPDIR/bundle"
test ! -e "$TMPDIR/demo/manifest.json"
.venv/bin/python -m auto_video worker run "$TMPDIR/bundle"
test -e "$TMPDIR/bundle/result.json"
test -e "$TMPDIR/bundle/outputs/generated/clips/S01.mp4"
.venv/bin/python -m auto_video worker import "$TMPDIR/demo" "$TMPDIR/bundle"
test -e "$TMPDIR/demo/manifest.json"
test -e "$TMPDIR/demo/generated/clips/S01.mp4"
.venv/bin/python -m auto_video jobs status "$TMPDIR/demo" >/tmp/auto_video_worker_jobs_status.json
.venv/bin/python -m auto_video assemble "$TMPDIR/demo" --dry-run >/tmp/auto_video_worker_render_plan.json
.venv/bin/python -m auto_video probe "$TMPDIR/demo" --dry-run >/tmp/auto_video_worker_probe_report.json
```

Expected:

- Export exits 0 and does not create project `manifest.json`.
- Worker run exits 0 and creates `result.json`.
- Import exits 0 and creates project generated clip and manifest.
- `jobs status`, `assemble --dry-run`, and `probe --dry-run` exit 0.

- [ ] **Step 3: Check git status**

Run:

```bash
git status --short --branch
```

Expected: clean working tree on `main`.

- [ ] **Step 4: Push to GitHub**

Run:

```bash
git push origin main
```

Expected: `main` is pushed to `origin/main`.

## Self-Review

Spec coverage:

- Worker bundle layout is covered by Task 1.
- Bundle export, job JSON, project snapshots, refs, outputs, and logs directories are covered by Task 1.
- Export not writing `manifest.json` is covered by Task 1 and Task 4.
- Force behavior for existing bundle directories is covered by Task 1 and Task 4.
- Worker run, `outputs/`, `result.json`, and `logs/worker.log` are covered by Task 2.
- Running without the source project path is covered by Task 2.
- Importing results and updating manifest legacy fields is covered by Task 3.
- Failed result import without legacy clip fields is covered by Task 3.
- CLI `worker export|run|import` is covered by Task 4.
- README workflow is covered by Task 5.
- Full verification and remote sync are covered by Task 6.

Intentional gaps:

- Real cloud transport, object storage, SSH/SCP/rsync, async polling, provider-specific wrappers, Docker, and GPU runtime installation remain future work.
