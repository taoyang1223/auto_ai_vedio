# Provider Job Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a provider-neutral job runtime so mock, API, and cloud GPU backends can share one generation contract.

**Architecture:** Add typed job records between the prompt planner and provider gateway, persist those records in `manifest.json`, and migrate existing `images`/`generate` commands to execute through the job runtime. Existing MVP behavior remains compatible while new `auto-video jobs plan|submit|status` commands expose the runtime directly.

**Tech Stack:** Python 3.12, dataclasses, pathlib, JSON/YAML, argparse, pytest, existing `auto_video` package.

---

## File Map

- Create `src/auto_video/jobs.py`: job dataclasses, status/kind validation, serialization, output path helpers, provider-result-to-asset conversion.
- Create `src/auto_video/job_builder.py`: convert `Project` and selected `ShotPlan` records into `GenerationJob` objects.
- Create `src/auto_video/job_store.py`: persist job records and provider results into `manifest.json`.
- Modify `src/auto_video/models.py`: add provider configuration dataclass and `ProjectConfig.providers`.
- Modify `src/auto_video/project.py`: parse `providers:` config from `project.yaml`.
- Modify `src/auto_video/manifest.py`: initialize `jobs` in new and existing manifests.
- Modify `src/auto_video/providers/base.py`: add job provider protocol.
- Modify `src/auto_video/providers/mock.py`: add `execute_job()` while preserving existing image/video methods.
- Modify `src/auto_video/pipeline.py`: route image/video generation through job planning/submission.
- Modify `src/auto_video/cli.py`: add `jobs plan`, `jobs submit`, and `jobs status`.
- Modify `README.md`: document the provider job workflow.
- Test with `tests/test_jobs.py`, `tests/test_job_builder.py`, `tests/test_job_store.py`, `tests/test_provider_jobs.py`, `tests/test_job_pipeline.py`, `tests/test_cli_jobs.py`, and the existing suite.

## Task 1: Job Models

**Files:**
- Create: `src/auto_video/jobs.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write failing job model tests**

Create `tests/test_jobs.py`:

```python
from pathlib import Path

import pytest

from auto_video.errors import ConfigError
from auto_video.jobs import (
    GenerationJob,
    ProviderControls,
    ProviderReference,
    ProviderResult,
    make_job_id,
    relative_output_path,
)


def test_make_job_id_is_stable():
    assert make_job_id("demo_ad", "S01", "video", "mock") == "demo_ad:S01:video:mock"


def test_generation_job_round_trips_to_manifest_dict():
    job = GenerationJob(
        id="demo_ad:S01:video:mock",
        project_name="demo_ad",
        shot_id="S01",
        kind="video",
        provider="mock",
        prompt="A tired person at a cold desk",
        negative_prompt="text, watermark",
        duration=5.0,
        output_path="generated/clips/S01.mp4",
        refs=(
            ProviderReference(
                path="assets/refs/S01.txt",
                type="text",
                role="first_frame",
                usage="preserve_subject",
                exists=True,
            ),
        ),
        controls=ProviderControls(
            visual_prompt="A tired person at a cold desk",
            camera_motion="slow_dolly_in",
            environment_motion="screen flicker",
            performance="tired breathing",
            lighting="cold fluorescent light",
            audio_intent="quiet room tone",
            subtitle="Late night again",
            negative_prompt="text, watermark",
            aspect_ratio="9:16",
            width=1080,
            height=1920,
            fps=30,
        ),
        created_at="2026-06-26T00:00:00Z",
        updated_at="2026-06-26T00:00:00Z",
    )

    data = job.to_dict()
    restored = GenerationJob.from_dict(data)

    assert data["id"] == "demo_ad:S01:video:mock"
    assert data["refs"][0]["role"] == "first_frame"
    assert data["controls"]["camera_motion"] == "slow_dolly_in"
    assert restored == job


def test_provider_result_maps_video_to_legacy_clip_asset():
    result = ProviderResult(
        job_id="demo_ad:S01:video:mock",
        shot_id="S01",
        kind="video",
        provider="mock",
        status="succeeded",
        path=Path("/tmp/demo/generated/clips/S01.mp4"),
        duration=5.0,
    )

    asset = result.to_asset_result()

    assert asset.kind == "clip"
    assert asset.status == "generated"
    assert asset.path == Path("/tmp/demo/generated/clips/S01.mp4")


def test_relative_output_path_uses_expected_kind_directories():
    assert relative_output_path("S01", "image") == "generated/images/S01.txt"
    assert relative_output_path("S01", "video") == "generated/clips/S01.mp4"
    assert relative_output_path("S01", "audio") == "generated/audio/S01.wav"


def test_invalid_job_kind_is_config_error():
    with pytest.raises(ConfigError) as exc:
        relative_output_path("S01", "mesh")
    assert "job kind" in str(exc.value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_jobs.py -v
```

Expected: FAIL because `auto_video.jobs` does not exist.

- [ ] **Step 3: Implement job models**

Create `src/auto_video/jobs.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import ConfigError, ProviderError
from .models import AssetResult

JOB_KINDS = {"image", "video", "audio"}
JOB_STATUSES = {"planned", "queued", "running", "succeeded", "failed", "retryable_failed"}


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _require_value(value: str, allowed: set[str], field_name: str) -> None:
    if value not in allowed:
        allowed_list = ", ".join(sorted(allowed))
        raise ConfigError(
            f"{field_name} has unsupported value {value!r}; allowed values: {allowed_list}",
            fix=f"Use one of: {allowed_list}.",
        )


def make_job_id(project_name: str, shot_id: str, kind: str, provider: str) -> str:
    _require_value(kind, JOB_KINDS, "job kind")
    return f"{project_name}:{shot_id}:{kind}:{provider}"


def relative_output_path(shot_id: str, kind: str) -> str:
    _require_value(kind, JOB_KINDS, "job kind")
    if kind == "image":
        return f"generated/images/{shot_id}.txt"
    if kind == "video":
        return f"generated/clips/{shot_id}.mp4"
    return f"generated/audio/{shot_id}.wav"


def legacy_asset_kind(kind: str) -> str:
    _require_value(kind, JOB_KINDS, "job kind")
    if kind == "video":
        return "clip"
    return kind


@dataclass(frozen=True)
class ProviderReference:
    path: str
    type: str
    role: str
    usage: str
    exists: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderReference":
        return cls(
            path=str(data["path"]),
            type=str(data["type"]),
            role=str(data["role"]),
            usage=str(data["usage"]),
            exists=bool(data["exists"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderControls:
    visual_prompt: str
    camera_motion: str
    environment_motion: str
    performance: str
    lighting: str
    audio_intent: str
    subtitle: str
    negative_prompt: str
    aspect_ratio: str
    width: int
    height: int
    fps: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderControls":
        return cls(
            visual_prompt=str(data.get("visual_prompt", "")),
            camera_motion=str(data.get("camera_motion", "")),
            environment_motion=str(data.get("environment_motion", "")),
            performance=str(data.get("performance", "")),
            lighting=str(data.get("lighting", "")),
            audio_intent=str(data.get("audio_intent", "")),
            subtitle=str(data.get("subtitle", "")),
            negative_prompt=str(data.get("negative_prompt", "")),
            aspect_ratio=str(data.get("aspect_ratio", "9:16")),
            width=int(data.get("width", 1080)),
            height=int(data.get("height", 1920)),
            fps=int(data.get("fps", 30)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GenerationJob:
    id: str
    project_name: str
    shot_id: str
    kind: str
    provider: str
    prompt: str
    negative_prompt: str
    duration: float | None
    output_path: str
    refs: tuple[ProviderReference, ...] = ()
    controls: ProviderControls | None = None
    status: str = "planned"
    attempts: int = 0
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    provider_job_id: str | None = None
    error: str | None = None
    retryable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_value(self.kind, JOB_KINDS, "job kind")
        _require_value(self.status, JOB_STATUSES, "job status")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GenerationJob":
        controls_data = data.get("controls")
        return cls(
            id=str(data["id"]),
            project_name=str(data["project_name"]),
            shot_id=str(data["shot_id"]),
            kind=str(data["kind"]),
            provider=str(data["provider"]),
            prompt=str(data.get("prompt", "")),
            negative_prompt=str(data.get("negative_prompt", "")),
            duration=float(data["duration"]) if data.get("duration") is not None else None,
            output_path=str(data["output_path"]),
            refs=tuple(ProviderReference.from_dict(ref) for ref in data.get("refs", [])),
            controls=ProviderControls.from_dict(controls_data) if controls_data else None,
            status=str(data.get("status", "planned")),
            attempts=int(data.get("attempts", 0)),
            created_at=str(data["created_at"]) if data.get("created_at") else utc_now_iso(),
            updated_at=str(data["updated_at"]) if data.get("updated_at") else utc_now_iso(),
            provider_job_id=data.get("provider_job_id"),
            error=data.get("error"),
            retryable=bool(data.get("retryable", False)),
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "shot_id": self.shot_id,
            "kind": self.kind,
            "provider": self.provider,
            "status": self.status,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "duration": self.duration,
            "output_path": self.output_path,
            "refs": [ref.to_dict() for ref in self.refs],
            "controls": self.controls.to_dict() if self.controls else None,
            "attempts": self.attempts,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "provider_job_id": self.provider_job_id,
            "error": self.error,
            "retryable": self.retryable,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ProviderResult:
    job_id: str
    shot_id: str
    kind: str
    provider: str
    status: str
    path: Path | None = None
    duration: float | None = None
    provider_job_id: str | None = None
    error: str | None = None
    retryable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_value(self.kind, JOB_KINDS, "job kind")
        _require_value(self.status, JOB_STATUSES, "job status")

    def to_asset_result(self) -> AssetResult:
        if self.path is None:
            raise ProviderError(
                f"provider result {self.job_id} has no output path",
                fix="Only successful provider results can be converted to legacy assets.",
            )
        return AssetResult(
            shot_id=self.shot_id,
            provider=self.provider,
            path=self.path,
            kind=legacy_asset_kind(self.kind),
            duration=self.duration,
            status="generated" if self.status == "succeeded" else "failed",
            error=self.error,
            retryable=self.retryable,
        )
```

- [ ] **Step 4: Run job model tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_jobs.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/auto_video/jobs.py tests/test_jobs.py
git commit -m "feat: add generation job models"
```

## Task 2: Provider Config And Job Builder

**Files:**
- Modify: `src/auto_video/models.py`
- Modify: `src/auto_video/project.py`
- Create: `src/auto_video/job_builder.py`
- Test: `tests/test_job_builder.py`

- [ ] **Step 1: Write failing job builder tests**

Create `tests/test_job_builder.py`:

```python
from auto_video.job_builder import build_jobs
from auto_video.project import load_project


def test_build_video_job_preserves_seedance_style_controls(demo_project_files):
    project = load_project(demo_project_files)

    jobs = build_jobs(project, kind="video", provider_name="mock")

    assert len(jobs) == 1
    job = jobs[0]
    assert job.id == "demo_ad:S01:video:mock"
    assert job.output_path == "generated/clips/S01.mp4"
    assert job.duration == 5.0
    assert job.refs[0].path == "assets/refs/S01.txt"
    assert job.refs[0].exists is True
    assert job.controls.camera_motion == "slow_dolly_in"
    assert job.controls.environment_motion == "screen flicker"
    assert job.controls.audio_intent == "quiet room tone"
    assert "A tired person at a cold desk" in job.prompt


def test_build_jobs_uses_only_filter(demo_project_files):
    project = load_project(demo_project_files)

    jobs = build_jobs(project, kind="video", provider_name="mock", only={"S99"})

    assert jobs == []


def test_project_loader_reads_provider_config(demo_project_files):
    (demo_project_files / "project.yaml").write_text(
        """
name: demo_ad
aspect_ratio: "9:16"
width: 1080
height: 1920
fps: 30
default_video_provider: mock
default_image_provider: mock
default_audio_provider: mock
providers:
  mock:
    mode: local
    timeout_seconds: 45
    max_attempts: 3
render:
  transition:
    type: fade
    duration: 0.6
  bgm_volume: 0.2
""".strip(),
        encoding="utf-8",
    )

    project = load_project(demo_project_files)

    assert project.config.providers["mock"].mode == "local"
    assert project.config.providers["mock"].timeout_seconds == 45
    assert project.config.providers["mock"].max_attempts == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_job_builder.py -v
```

Expected: FAIL because `auto_video.job_builder` does not exist and provider config is not parsed.

- [ ] **Step 3: Add provider config to models**

Modify `src/auto_video/models.py`.

Add this dataclass after `RenderConfig`:

```python
@dataclass(frozen=True)
class ProviderConfig:
    mode: str = "local"
    endpoint_env: str | None = None
    token_env: str | None = None
    timeout_seconds: int = 900
    max_attempts: int = 1
    options: dict[str, Any] = field(default_factory=dict)
```

Change `ProjectConfig` to include:

```python
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
```

Keep the existing provider enum validation in `ProjectConfig.__post_init__`.

- [ ] **Step 4: Parse provider config in project loader**

Modify imports in `src/auto_video/project.py` to include `ProviderConfig`:

```python
    ProviderConfig,
```

Add this helper above `_project_config`:

```python
def _provider_configs(data: dict[str, Any]) -> dict[str, ProviderConfig]:
    providers = data.get("providers") or {}
    if not isinstance(providers, dict):
        raise ConfigError("providers must be a mapping", fix="Use provider names as keys under providers.")
    result: dict[str, ProviderConfig] = {}
    for name, raw in providers.items():
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ConfigError(f"provider {name} config must be a mapping", fix="Use key/value provider settings.")
        known = {"mode", "endpoint_env", "token_env", "timeout_seconds", "max_attempts"}
        options = {key: value for key, value in raw.items() if key not in known}
        result[str(name)] = ProviderConfig(
            mode=str(raw.get("mode", "local")),
            endpoint_env=raw.get("endpoint_env"),
            token_env=raw.get("token_env"),
            timeout_seconds=int(raw.get("timeout_seconds", 900)),
            max_attempts=int(raw.get("max_attempts", 1)),
            options=options,
        )
    result.setdefault("mock", ProviderConfig(mode="local", timeout_seconds=30, max_attempts=1))
    return result
```

In `_project_config`, pass:

```python
        providers=_provider_configs(data),
```

- [ ] **Step 5: Implement job builder**

Create `src/auto_video/job_builder.py`:

```python
from __future__ import annotations

from .jobs import (
    GenerationJob,
    ProviderControls,
    ProviderReference,
    make_job_id,
    relative_output_path,
    utc_now_iso,
)
from .models import Project, ShotPlan
from .project import resolve_project_path
from .prompts import plan_prompt


def _default_provider(project: Project, kind: str) -> str:
    if kind == "image":
        return project.config.default_image_provider
    if kind == "audio":
        return project.config.default_audio_provider
    return project.config.default_video_provider


def _select_shots(project: Project, only: set[str] | None = None):
    for shot in project.shots:
        if only and shot.id not in only:
            continue
        yield shot


def _provider_refs(project: Project, shot: ShotPlan) -> tuple[ProviderReference, ...]:
    refs: list[ProviderReference] = []
    for ref in shot.refs:
        refs.append(
            ProviderReference(
                path=ref.path,
                type=ref.type,
                role=ref.role,
                usage=ref.usage,
                exists=resolve_project_path(project.config.root, ref.path).exists(),
            )
        )
    return tuple(refs)


def _controls(project: Project, shot: ShotPlan) -> ProviderControls:
    return ProviderControls(
        visual_prompt=shot.visual_prompt,
        camera_motion=shot.camera_motion,
        environment_motion=shot.environment_motion,
        performance=shot.performance,
        lighting=shot.lighting,
        audio_intent=shot.audio_intent,
        subtitle=shot.subtitle,
        negative_prompt=shot.negative_prompt,
        aspect_ratio=project.config.aspect_ratio,
        width=project.config.width,
        height=project.config.height,
        fps=project.config.fps,
    )


def build_jobs(
    project: Project,
    *,
    kind: str,
    provider_name: str | None = None,
    only: set[str] | None = None,
) -> list[GenerationJob]:
    jobs: list[GenerationJob] = []
    for shot in _select_shots(project, only):
        provider = provider_name or shot.provider or _default_provider(project, kind)
        now = utc_now_iso()
        jobs.append(
            GenerationJob(
                id=make_job_id(project.config.name, shot.id, kind, provider),
                project_name=project.config.name,
                shot_id=shot.id,
                kind=kind,
                provider=provider,
                prompt=plan_prompt(shot, provider=provider),
                negative_prompt=shot.negative_prompt,
                duration=shot.duration if kind in {"video", "audio"} else None,
                output_path=relative_output_path(shot.id, kind),
                refs=_provider_refs(project, shot),
                controls=_controls(project, shot),
                created_at=now,
                updated_at=now,
            )
        )
    return jobs
```

- [ ] **Step 6: Run job builder tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_job_builder.py -v
```

Expected: PASS.

- [ ] **Step 7: Run existing model and project loader tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_models_validation.py tests/test_project_loader.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/auto_video/models.py src/auto_video/project.py src/auto_video/job_builder.py tests/test_job_builder.py
git commit -m "feat: build provider generation jobs"
```

## Task 3: Manifest Job Store

**Files:**
- Modify: `src/auto_video/manifest.py`
- Create: `src/auto_video/job_store.py`
- Test: `tests/test_job_store.py`

- [ ] **Step 1: Write failing job store tests**

Create `tests/test_job_store.py`:

```python
import json
from pathlib import Path

from auto_video.job_builder import build_jobs
from auto_video.job_store import JobStore
from auto_video.jobs import ProviderResult
from auto_video.project import load_project


def test_job_store_persists_planned_job(demo_project_files):
    project = load_project(demo_project_files)
    job = build_jobs(project, kind="video", provider_name="mock")[0]
    store = JobStore(demo_project_files / "manifest.json", project_name=project.config.name)

    store.record_job(job)
    store.save()

    data = json.loads((demo_project_files / "manifest.json").read_text(encoding="utf-8"))
    assert "jobs" in data
    assert data["jobs"]["demo_ad:S01:video:mock"]["status"] == "planned"
    assert data["jobs"]["demo_ad:S01:video:mock"]["output_path"] == "generated/clips/S01.mp4"


def test_job_store_records_success_result_and_legacy_clip(demo_project_files):
    project = load_project(demo_project_files)
    job = build_jobs(project, kind="video", provider_name="mock")[0]
    clip = demo_project_files / "generated" / "clips" / "S01.mp4"
    store = JobStore(demo_project_files / "manifest.json", project_name=project.config.name)

    store.record_job(job)
    store.record_result(
        ProviderResult(
            job_id=job.id,
            shot_id="S01",
            kind="video",
            provider="mock",
            status="succeeded",
            path=clip,
            duration=5.0,
        )
    )
    store.save()

    data = json.loads((demo_project_files / "manifest.json").read_text(encoding="utf-8"))
    assert data["jobs"][job.id]["status"] == "succeeded"
    assert data["jobs"][job.id]["attempts"] == 1
    assert data["shots"]["S01"]["clip"] == "generated/clips/S01.mp4"
    assert data["shots"]["S01"]["status"] == "generated"


def test_job_store_records_retryable_failure_without_clip(demo_project_files):
    project = load_project(demo_project_files)
    job = build_jobs(project, kind="video", provider_name="mock")[0]
    store = JobStore(demo_project_files / "manifest.json", project_name=project.config.name)

    store.record_job(job)
    store.record_result(
        ProviderResult(
            job_id=job.id,
            shot_id="S01",
            kind="video",
            provider="mock",
            status="retryable_failed",
            error="RateLimit",
            retryable=True,
        )
    )
    store.save()

    data = json.loads((demo_project_files / "manifest.json").read_text(encoding="utf-8"))
    assert data["jobs"][job.id]["status"] == "retryable_failed"
    assert data["jobs"][job.id]["error"] == "RateLimit"
    assert data["jobs"][job.id]["retryable"] is True
    assert "clip" not in data.get("shots", {}).get("S01", {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_job_store.py -v
```

Expected: FAIL because `auto_video.job_store` does not exist.

- [ ] **Step 3: Initialize `jobs` in manifest store**

Modify `src/auto_video/manifest.py`.

In the new manifest data, add:

```python
                "jobs": {},
```

After the existing `setdefault("renders", {})`, add:

```python
        self.data.setdefault("jobs", {})
```

- [ ] **Step 4: Implement job store**

Create `src/auto_video/job_store.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from .jobs import GenerationJob, ProviderResult, utc_now_iso
from .manifest import ManifestStore


class JobStore:
    def __init__(self, path: Path, *, project_name: str):
        self.manifest = ManifestStore(path, project_name=project_name)
        self.manifest.data.setdefault("jobs", {})

    @property
    def data(self) -> dict[str, Any]:
        return self.manifest.data

    def record_job(self, job: GenerationJob) -> None:
        self.data["jobs"][job.id] = job.to_dict()

    def record_result(self, result: ProviderResult) -> None:
        now = utc_now_iso()
        job = self.data["jobs"].setdefault(
            result.job_id,
            {
                "id": result.job_id,
                "shot_id": result.shot_id,
                "kind": result.kind,
                "provider": result.provider,
                "attempts": 0,
                "created_at": now,
                "metadata": {},
            },
        )
        job["status"] = result.status
        job["updated_at"] = now
        job["attempts"] = int(job.get("attempts", 0)) + 1
        job["retryable"] = result.retryable
        job["provider_job_id"] = result.provider_job_id
        job["error"] = result.error
        job["metadata"] = result.metadata
        if result.path is not None:
            job["output_path"] = self.manifest._relative(result.path)
        if result.duration is not None:
            job["duration"] = result.duration
        if result.status == "succeeded":
            self.manifest.record_asset(result.to_asset_result())
        elif result.status in {"failed", "retryable_failed"}:
            shot = self.data["shots"].setdefault(result.shot_id, {})
            shot["status"] = "failed"
            shot["provider"] = result.provider
            if result.error:
                shot["error"] = result.error
            if result.retryable:
                shot["retryable"] = True

    def jobs(self) -> dict[str, dict[str, Any]]:
        return self.data.get("jobs", {})

    def summary(self) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        for job in self.jobs().values():
            status = str(job.get("status", "unknown"))
            by_status[status] = by_status.get(status, 0) + 1
        return {"total": len(self.jobs()), "by_status": by_status, "jobs": self.jobs()}

    def save(self) -> None:
        self.manifest.save()
```

- [ ] **Step 5: Run job store tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_job_store.py -v
```

Expected: PASS.

- [ ] **Step 6: Run manifest tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_manifest.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/auto_video/manifest.py src/auto_video/job_store.py tests/test_job_store.py
git commit -m "feat: persist generation jobs in manifest"
```

## Task 4: Mock Provider Job Execution

**Files:**
- Modify: `src/auto_video/providers/base.py`
- Modify: `src/auto_video/providers/mock.py`
- Test: `tests/test_provider_jobs.py`

- [ ] **Step 1: Write failing provider job tests**

Create `tests/test_provider_jobs.py`:

```python
from auto_video.job_builder import build_jobs
from auto_video.project import load_project
from auto_video.providers.mock import MockProvider


def test_mock_provider_executes_video_job(demo_project_files):
    project = load_project(demo_project_files)
    job = build_jobs(project, kind="video", provider_name="mock")[0]
    provider = MockProvider()

    result = provider.execute_job(job, project.config.root)

    assert result.job_id == "demo_ad:S01:video:mock"
    assert result.status == "succeeded"
    assert result.path == demo_project_files / "generated" / "clips" / "S01.mp4"
    assert result.duration == 5.0
    assert result.path.read_text(encoding="utf-8").startswith("mock video")


def test_mock_provider_executes_image_job(demo_project_files):
    project = load_project(demo_project_files)
    job = build_jobs(project, kind="image", provider_name="mock")[0]
    provider = MockProvider()

    result = provider.execute_job(job, project.config.root)

    assert result.job_id == "demo_ad:S01:image:mock"
    assert result.status == "succeeded"
    assert result.path == demo_project_files / "generated" / "images" / "S01.txt"
    assert result.path.read_text(encoding="utf-8").startswith("mock image")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_provider_jobs.py -v
```

Expected: FAIL because `MockProvider.execute_job` does not exist.

- [ ] **Step 3: Add job provider protocol**

Modify `src/auto_video/providers/base.py`.

Add imports:

```python
from pathlib import Path

from auto_video.jobs import GenerationJob, ProviderResult
```

Add this protocol after `VideoProvider`:

```python
class JobProvider(Protocol):
    name: str

    def execute_job(self, job: GenerationJob, project_root: Path) -> ProviderResult:
        ...
```

- [ ] **Step 4: Add job execution to mock provider**

Modify `src/auto_video/providers/mock.py`.

Add imports:

```python
from pathlib import Path

from auto_video.jobs import GenerationJob, ProviderResult
```

Add this method inside `MockProvider`:

```python
    def execute_job(self, job: GenerationJob, project_root: Path) -> ProviderResult:
        output_path = project_root / job.output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if job.kind == "image":
            output_path.write_text(f"mock image for {job.shot_id}\n{job.prompt}\n", encoding="utf-8")
            duration = None
        elif job.kind == "video":
            output_path.write_text(f"mock video for {job.shot_id}\n{job.prompt}\n", encoding="utf-8")
            duration = job.duration
        else:
            output_path.write_text(f"mock audio for {job.shot_id}\n{job.prompt}\n", encoding="utf-8")
            duration = job.duration
        return ProviderResult(
            job_id=job.id,
            shot_id=job.shot_id,
            kind=job.kind,
            provider=self.name,
            status="succeeded",
            path=output_path,
            duration=duration,
            metadata={"mock": True},
        )
```

Leave `generate_image()` and `generate_video()` unchanged for this task.

- [ ] **Step 5: Run provider job tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_provider_jobs.py -v
```

Expected: PASS.

- [ ] **Step 6: Run existing mock pipeline tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_mock_pipeline.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/auto_video/providers/base.py src/auto_video/providers/mock.py tests/test_provider_jobs.py
git commit -m "feat: execute jobs with mock provider"
```

## Task 5: Pipeline Runtime Migration

**Files:**
- Modify: `src/auto_video/pipeline.py`
- Test: `tests/test_job_pipeline.py`
- Test: existing `tests/test_mock_pipeline.py`
- Test: existing `tests/test_render_probe.py`

- [ ] **Step 1: Write failing job pipeline tests**

Create `tests/test_job_pipeline.py`:

```python
import json

from auto_video.pipeline import plan_jobs, submit_jobs
from auto_video.project import load_project


def test_plan_jobs_does_not_write_manifest(demo_project_files):
    project = load_project(demo_project_files)

    plan = plan_jobs(project, kind="video", provider_name="mock")

    assert plan["dry_run"] is True
    assert plan["planned"][0]["id"] == "demo_ad:S01:video:mock"
    assert plan["planned"][0]["output_path"] == "generated/clips/S01.mp4"
    assert not (demo_project_files / "manifest.json").exists()


def test_submit_jobs_writes_clip_and_job_manifest(demo_project_files):
    project = load_project(demo_project_files)

    results = submit_jobs(project, kind="video", provider_name="mock")

    manifest = json.loads((demo_project_files / "manifest.json").read_text(encoding="utf-8"))
    assert results[0].job_id == "demo_ad:S01:video:mock"
    assert manifest["shots"]["S01"]["clip"] == "generated/clips/S01.mp4"
    assert manifest["jobs"]["demo_ad:S01:video:mock"]["status"] == "succeeded"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_job_pipeline.py -v
```

Expected: FAIL because `plan_jobs` and `submit_jobs` do not exist.

- [ ] **Step 3: Replace pipeline internals with job runtime**

Replace `src/auto_video/pipeline.py` with:

```python
from __future__ import annotations

from typing import Any

from .job_builder import build_jobs
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
) -> dict[str, Any]:
    return _plan_payload(build_jobs(project, kind=kind, provider_name=provider_name, only=only))


def submit_jobs(
    project: Project,
    *,
    kind: str,
    provider_name: str | None = None,
    only: set[str] | None = None,
) -> list[ProviderResult]:
    jobs = build_jobs(project, kind=kind, provider_name=provider_name, only=only)
    store = JobStore(project.config.root / "manifest.json", project_name=project.config.name)
    results: list[ProviderResult] = []
    for job in jobs:
        provider = get_provider(job.provider)
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
) -> dict[str, Any] | list[AssetResult]:
    if dry_run:
        return plan_jobs(project, kind="image", provider_name=provider_name, only=only)
    return _asset_results(submit_jobs(project, kind="image", provider_name=provider_name, only=only))


def generate_videos(
    project: Project,
    *,
    provider_name: str | None = None,
    dry_run: bool = False,
    only: set[str] | None = None,
) -> dict[str, Any] | list[AssetResult]:
    if dry_run:
        return plan_jobs(project, kind="video", provider_name=provider_name, only=only)
    return _asset_results(submit_jobs(project, kind="video", provider_name=provider_name, only=only))
```

- [ ] **Step 4: Run job pipeline tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_job_pipeline.py -v
```

Expected: PASS.

- [ ] **Step 5: Run existing generation/render tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_mock_pipeline.py tests/test_render_probe.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/auto_video/pipeline.py tests/test_job_pipeline.py
git commit -m "feat: route generation through job runtime"
```

## Task 6: CLI Jobs Commands

**Files:**
- Modify: `src/auto_video/cli.py`
- Test: `tests/test_cli_jobs.py`
- Test: existing `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI job tests**

Create `tests/test_cli_jobs.py`:

```python
import json
from pathlib import Path

from auto_video.cli import main


def test_cli_jobs_plan_does_not_write_manifest(tmp_path: Path, capsys):
    project = tmp_path / "demo"
    assert main(["init", str(project)]) == 0

    assert main(["jobs", "plan", str(project), "--provider", "mock", "--kind", "video"]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["dry_run"] is True
    assert payload["planned"][0]["id"] == "demo_ad:S01:video:mock"
    assert not (project / "manifest.json").exists()


def test_cli_jobs_submit_and_status(tmp_path: Path, capsys):
    project = tmp_path / "demo"
    assert main(["init", str(project)]) == 0

    assert main(["jobs", "submit", str(project), "--provider", "mock", "--kind", "video"]) == 0
    assert (project / "generated" / "clips" / "S01.mp4").exists()
    capsys.readouterr()

    assert main(["jobs", "status", str(project)]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["total"] == 1
    assert payload["by_status"]["succeeded"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli_jobs.py -v
```

Expected: FAIL because `jobs` CLI group is not implemented.

- [ ] **Step 3: Add CLI imports**

Modify `src/auto_video/cli.py` imports:

```python
from .job_store import JobStore
from .pipeline import generate_images, generate_videos, plan_jobs, submit_jobs
```

- [ ] **Step 4: Add jobs parser**

In `build_parser()` before `providers = sub.add_parser("providers")`, add:

```python
    jobs = sub.add_parser("jobs")
    jobs_sub = jobs.add_subparsers(dest="jobs_command")

    jobs_plan = jobs_sub.add_parser("plan")
    jobs_plan.add_argument("project")
    jobs_plan.add_argument("--provider")
    jobs_plan.add_argument("--kind", choices=["image", "video", "audio"], default="video")
    jobs_plan.add_argument("--only")

    jobs_submit = jobs_sub.add_parser("submit")
    jobs_submit.add_argument("project")
    jobs_submit.add_argument("--provider")
    jobs_submit.add_argument("--kind", choices=["image", "video", "audio"], default="video")
    jobs_submit.add_argument("--only")

    jobs_status = jobs_sub.add_parser("status")
    jobs_status.add_argument("project")
```

- [ ] **Step 5: Add jobs command handling**

In `main()`, before the existing `providers` block, add:

```python
        if args.command == "jobs" and args.jobs_command == "plan":
            result = plan_jobs(
                load_project(args.project),
                kind=args.kind,
                provider_name=args.provider,
                only=_csv(args.only),
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "jobs" and args.jobs_command == "submit":
            project = load_project(args.project)
            results = submit_jobs(
                project,
                kind=args.kind,
                provider_name=args.provider,
                only=_csv(args.only),
            )
            print(
                json.dumps(
                    {"submitted": [result.job_id for result in results], "count": len(results)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "jobs" and args.jobs_command == "status":
            project = load_project(args.project)
            store = JobStore(project.config.root / "manifest.json", project_name=project.config.name)
            print(json.dumps(store.summary(), ensure_ascii=False, indent=2))
            return 0
```

- [ ] **Step 6: Run CLI job tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli_jobs.py -v
```

Expected: PASS.

- [ ] **Step 7: Run existing CLI tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/auto_video/cli.py tests/test_cli_jobs.py
git commit -m "feat: add job runtime CLI commands"
```

## Task 7: Documentation And Example Workflow

**Files:**
- Modify: `README.md`
- Test: `tests/test_cli_jobs.py`

- [ ] **Step 1: Add checked-in example job workflow test**

Append to `tests/test_cli_jobs.py`:

```python
def test_checked_in_example_job_workflow(capsys):
    assert main(["jobs", "plan", "examples/demo_project", "--provider", "mock", "--kind", "video"]) == 0
    plan_output = json.loads(capsys.readouterr().out)
    assert plan_output["planned"][0]["id"] == "demo_ad:S01:video:mock"
```

Do not submit against `examples/demo_project` in this test because submission would create generated files inside the checked-in example directory.

- [ ] **Step 2: Run test to verify current behavior**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli_jobs.py::test_checked_in_example_job_workflow -v
```

Expected: PASS if Task 6 is complete.

- [ ] **Step 3: Update README**

Modify `README.md` MVP workflow block to include:

```bash
.venv/bin/python -m auto_video jobs plan demo_project --provider mock --kind video
.venv/bin/python -m auto_video jobs submit demo_project --provider mock --kind video
.venv/bin/python -m auto_video jobs status demo_project
```

Add this section after "Design":

```markdown
## Provider Job Runtime

Phase 2 routes generation through provider-neutral jobs:

    .venv/bin/python -m auto_video jobs plan demo_project --provider mock --kind video
    .venv/bin/python -m auto_video jobs submit demo_project --provider mock --kind video
    .venv/bin/python -m auto_video jobs status demo_project

`jobs plan` prints deterministic job records without writing `manifest.json`.
`jobs submit` executes the selected provider and records both legacy shot assets and provider job records in `manifest.json`.
The mock provider stays offline and deterministic, so tests do not need API keys, network, FFmpeg, or cloud GPU access.
```

- [ ] **Step 4: Run docs workflow test**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli_jobs.py::test_checked_in_example_job_workflow -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md tests/test_cli_jobs.py
git commit -m "docs: document provider job workflow"
```

## Task 8: Full Verification And Remote Sync

**Files:**
- No source changes expected unless verification exposes an issue.

- [ ] **Step 1: Run full test suite**

Run:

```bash
.venv/bin/python -m pytest -v
```

Expected: all tests PASS.

- [ ] **Step 2: Run CLI smoke for old and new workflows**

Run:

```bash
set -euo pipefail
TMPDIR="$(mktemp -d)"
.venv/bin/python -m auto_video init "$TMPDIR/demo"
.venv/bin/python -m auto_video validate "$TMPDIR/demo"
.venv/bin/python -m auto_video jobs plan "$TMPDIR/demo" --provider mock --kind video >/tmp/auto_video_jobs_plan.json
test ! -e "$TMPDIR/demo/manifest.json"
.venv/bin/python -m auto_video jobs submit "$TMPDIR/demo" --provider mock --kind video >/tmp/auto_video_jobs_submit.json
test -e "$TMPDIR/demo/manifest.json"
test -e "$TMPDIR/demo/generated/clips/S01.mp4"
.venv/bin/python -m auto_video jobs status "$TMPDIR/demo" >/tmp/auto_video_jobs_status.json
.venv/bin/python -m auto_video generate "$TMPDIR/demo" --provider mock
.venv/bin/python -m auto_video assemble "$TMPDIR/demo" --dry-run >/tmp/auto_video_render_plan.json
.venv/bin/python -m auto_video probe "$TMPDIR/demo" --dry-run >/tmp/auto_video_probe_report.json
```

Expected:

- `jobs plan` exits 0 and does not create `manifest.json`.
- `jobs submit` exits 0 and creates `manifest.json`.
- `generated/clips/S01.mp4` exists.
- legacy `generate` still exits 0.
- `assemble --dry-run` and `probe --dry-run` still exit 0.

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

- Job models are covered by Task 1.
- Deterministic job id strategy is covered by Task 1 and Task 2.
- Provider references and Seedance-style controls are covered by Task 2.
- Provider configuration parsing is covered by Task 2.
- Manifest `jobs` storage is covered by Task 3.
- Mock provider job execution is covered by Task 4.
- Existing pipeline migration is covered by Task 5.
- CLI `jobs plan`, `jobs submit`, and `jobs status` are covered by Task 6.
- README and checked-in example planning are covered by Task 7.
- Full verification and remote sync are covered by Task 8.

Intentional gaps:

- Real Seedance, Wan, cloud GPU, object storage, async polling, retries, and provider capability negotiation remain future work from the spec.
- Audio jobs are modeled and accepted by the runtime, but there is no real audio provider beyond deterministic mock text output.
