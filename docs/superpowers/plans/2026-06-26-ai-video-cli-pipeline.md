# AI Video CLI Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the MVP CLI pipeline that validates AI video projects, plans multimodal shot prompts, runs mock generation, manages manifests, dry-runs rendering, and probes generated artifacts.

**Architecture:** Implement a small Python package under `src/auto_video` with clear service boundaries: CLI, project loading, schema validation, manifest registry, prompt planning, provider gateway, render planning, and probe reporting. The first implementation uses deterministic mock providers so default tests run without network, API keys, cloud GPU, or large media files.

**Tech Stack:** Python 3.12, argparse, dataclasses, pathlib, json, PyYAML, pytest, subprocess wrappers for future FFmpeg/ffprobe integration.

---

## File Structure

Create these files:

```text
pyproject.toml
README.md
.gitignore
src/auto_video/__init__.py
src/auto_video/__main__.py
src/auto_video/cli.py
src/auto_video/errors.py
src/auto_video/models.py
src/auto_video/project.py
src/auto_video/validation.py
src/auto_video/manifest.py
src/auto_video/prompts.py
src/auto_video/providers/__init__.py
src/auto_video/providers/base.py
src/auto_video/providers/mock.py
src/auto_video/pipeline.py
src/auto_video/render.py
src/auto_video/probe.py
examples/demo_project/project.yaml
examples/demo_project/shots.json
examples/demo_project/assets/refs/S01.txt
tests/conftest.py
tests/test_models_validation.py
tests/test_project_loader.py
tests/test_manifest.py
tests/test_prompts.py
tests/test_mock_pipeline.py
tests/test_render_probe.py
tests/test_cli.py
```

Responsibilities:

- `cli.py`: Parse commands and call service functions. It should remain thin.
- `errors.py`: User-facing exception classes with clear repair guidance.
- `models.py`: Dataclasses and enum constants for config, shots, references, generation tasks, results, and plans.
- `project.py`: Load `project.yaml`, `shots.json`, and `manifest.json`; resolve safe project paths.
- `validation.py`: Validate project config, shots, providers, references, durations, and path containment.
- `manifest.py`: Read, write, and update manifest entries. It must respect dry-run behavior through callers.
- `prompts.py`: Convert structured shot fields into provider-specific prompt text.
- `providers/base.py`: Provider interfaces.
- `providers/mock.py`: Deterministic offline image/video/audio provider.
- `pipeline.py`: Coordinate image and video generation using project, manifest, prompt planner, and provider registry.
- `render.py`: Build render EDL and FFmpeg command plans. Dry-run returns plans without writing media.
- `probe.py`: Inspect manifest and media metadata through injectable runners.

## Task 1: Project Skeleton And Tooling

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `README.md`
- Create: `src/auto_video/__init__.py`
- Create: `src/auto_video/__main__.py`
- Create: `src/auto_video/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI smoke test**

Create `tests/test_cli.py`:

```python
from auto_video.cli import main


def test_cli_help_exits_successfully(capsys):
    code = main(["--help"])
    captured = capsys.readouterr()
    assert code == 0
    assert "auto-video" in captured.out
    assert "validate" in captured.out
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd /root/auto_ai_vedio
python3 -m pytest tests/test_cli.py::test_cli_help_exits_successfully -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'auto_video'`.

- [ ] **Step 3: Add package and test tooling**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "auto-ai-video"
version = "0.1.0"
description = "Seedance-inspired AI video production CLI pipeline"
requires-python = ">=3.12"
dependencies = [
  "PyYAML>=6.0.2"
]

[project.optional-dependencies]
dev = [
  "pytest>=8.2"
]

[project.scripts]
auto-video = "auto_video.cli:entrypoint"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

Create `.gitignore`:

```gitignore
__pycache__/
*.pyc
.pytest_cache/
.venv/
dist/
build/
*.egg-info/

# Generated AI video artifacts
generated/
renders/
reports/
*.mp4
*.mov
*.wav
*.mp3

# Local secrets
.env
config.toml
```

Create `README.md`:

```markdown
# auto_ai_vedio

Seedance-inspired AI video production CLI pipeline.

The MVP focuses on a local command-line workflow:

```bash
auto-video init demo_project
auto-video validate demo_project
auto-video images demo_project --dry-run
auto-video generate demo_project --dry-run
auto-video assemble demo_project --dry-run
auto-video probe demo_project --dry-run
```

See `docs/superpowers/specs/2026-06-26-ai-video-cli-pipeline-design.md` for the design.
```

Create `src/auto_video/__init__.py`:

```python
"""AI video production CLI pipeline."""

__version__ = "0.1.0"
```

Create `src/auto_video/__main__.py`:

```python
from .cli import entrypoint


if __name__ == "__main__":
    raise SystemExit(entrypoint())
```

Create `src/auto_video/cli.py`:

```python
from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="auto-video")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init")
    sub.add_parser("validate")
    sub.add_parser("images")
    sub.add_parser("generate")
    sub.add_parser("assemble")
    sub.add_parser("probe")
    providers = sub.add_parser("providers")
    providers.add_subparsers(dest="providers_command").add_parser("health")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    return 0


def entrypoint() -> int:
    return main()
```

- [ ] **Step 4: Run the smoke test**

Run:

```bash
cd /root/auto_ai_vedio
python3 -m pytest tests/test_cli.py::test_cli_help_exits_successfully -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore README.md src/auto_video tests/test_cli.py
git commit -m "chore: add Python CLI project skeleton"
```

## Task 2: Domain Models And User-Facing Errors

**Files:**
- Create: `src/auto_video/errors.py`
- Create: `src/auto_video/models.py`
- Test: `tests/test_models_validation.py`

- [ ] **Step 1: Write failing model tests**

Create `tests/test_models_validation.py`:

```python
import pytest

from auto_video.errors import ConfigError
from auto_video.models import AssetRef, ShotPlan


def test_asset_ref_rejects_unknown_role():
    with pytest.raises(ConfigError) as exc:
        AssetRef(path="assets/refs/S01.png", type="image", role="bad_role", usage="preserve_subject")
    assert "role" in str(exc.value)
    assert "bad_role" in str(exc.value)


def test_shot_plan_rejects_non_positive_duration():
    with pytest.raises(ConfigError) as exc:
        ShotPlan(id="S01", duration=0, visual_prompt="test")
    assert "duration" in str(exc.value)
    assert "S01" in str(exc.value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /root/auto_ai_vedio
python3 -m pytest tests/test_models_validation.py -v
```

Expected: FAIL because `auto_video.errors` and `auto_video.models` do not exist.

- [ ] **Step 3: Implement error classes**

Create `src/auto_video/errors.py`:

```python
from __future__ import annotations


class AutoVideoError(Exception):
    """Base class for user-facing auto-video errors."""

    category = "AutoVideoError"

    def __init__(self, message: str, *, fix: str | None = None):
        super().__init__(message)
        self.message = message
        self.fix = fix

    def __str__(self) -> str:
        if self.fix:
            return f"{self.category}: {self.message}\nFix: {self.fix}"
        return f"{self.category}: {self.message}"


class ConfigError(AutoVideoError):
    category = "ConfigError"


class AssetError(AutoVideoError):
    category = "AssetError"


class ProviderError(AutoVideoError):
    category = "ProviderError"


class RenderError(AutoVideoError):
    category = "RenderError"


class ProbeError(AutoVideoError):
    category = "ProbeError"
```

- [ ] **Step 4: Implement dataclasses and enum validation**

Create `src/auto_video/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigError

ASSET_TYPES = {"image", "video", "audio", "text"}
REFERENCE_ROLES = {
    "first_frame",
    "last_frame",
    "style_reference",
    "camera_reference",
    "motion_reference",
    "voice_reference",
    "bgm_reference",
    "environment_reference",
}
REFERENCE_USAGES = {
    "preserve_subject",
    "preserve_voice",
    "extract_style",
    "extract_camera_motion",
    "extract_action",
    "extract_audio_rhythm",
    "provide_context",
}
PROVIDERS = {"mock", "seedream", "seedance", "wan", "slideshow"}


def _require_enum(value: str, allowed: set[str], field_name: str) -> None:
    if value not in allowed:
        allowed_list = ", ".join(sorted(allowed))
        raise ConfigError(
            f"{field_name} has unsupported value {value!r}; allowed values: {allowed_list}",
            fix=f"Use one of: {allowed_list}.",
        )


@dataclass(frozen=True)
class AssetRef:
    path: str
    type: str
    role: str
    usage: str

    def __post_init__(self) -> None:
        _require_enum(self.type, ASSET_TYPES, "type")
        _require_enum(self.role, REFERENCE_ROLES, "role")
        _require_enum(self.usage, REFERENCE_USAGES, "usage")


@dataclass(frozen=True)
class RenderTransition:
    type: str = "fade"
    duration: float = 0.6


@dataclass(frozen=True)
class RenderText:
    text: str
    at: float


@dataclass(frozen=True)
class RenderConfig:
    transition: RenderTransition = field(default_factory=RenderTransition)
    bgm: str | None = None
    bgm_volume: float = 0.2
    subtitle_style: str = "default"
    brand: RenderText | None = None
    cta: RenderText | None = None


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    root: Path
    aspect_ratio: str = "9:16"
    width: int = 1080
    height: int = 1920
    fps: int = 30
    default_video_provider: str = "mock"
    default_image_provider: str = "mock"
    default_audio_provider: str = "mock"
    render: RenderConfig = field(default_factory=RenderConfig)

    def __post_init__(self) -> None:
        for field_name, provider in {
            "default_video_provider": self.default_video_provider,
            "default_image_provider": self.default_image_provider,
            "default_audio_provider": self.default_audio_provider,
        }.items():
            _require_enum(provider, PROVIDERS, field_name)


@dataclass(frozen=True)
class ShotPlan:
    id: str
    duration: float
    visual_prompt: str = ""
    title: str = ""
    intent: str = ""
    provider: str | None = None
    camera_motion: str = ""
    environment_motion: str = ""
    performance: str = ""
    lighting: str = ""
    audio_intent: str = ""
    subtitle: str = ""
    negative_prompt: str = ""
    refs: tuple[AssetRef, ...] = ()

    def __post_init__(self) -> None:
        if self.duration <= 0:
            raise ConfigError(
                f"shot {self.id} duration must be greater than 0; got {self.duration}",
                fix="Set duration to a positive number of seconds.",
            )
        if self.provider is not None:
            _require_enum(self.provider, PROVIDERS, f"shot {self.id} provider")


@dataclass(frozen=True)
class Project:
    config: ProjectConfig
    shots: tuple[ShotPlan, ...]
    manifest: dict[str, Any]


@dataclass(frozen=True)
class GenerationTask:
    project: ProjectConfig
    shot: ShotPlan
    prompt: str
    output_path: Path
    dry_run: bool = False


@dataclass(frozen=True)
class AssetResult:
    shot_id: str
    provider: str
    path: Path
    kind: str
    duration: float | None = None
    status: str = "generated"
    error: str | None = None
    retryable: bool = False
```

- [ ] **Step 5: Run model tests**

Run:

```bash
cd /root/auto_ai_vedio
python3 -m pytest tests/test_models_validation.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/auto_video/errors.py src/auto_video/models.py tests/test_models_validation.py
git commit -m "feat: add domain models and errors"
```

## Task 3: Project Loader And Schema Validation

**Files:**
- Create: `src/auto_video/project.py`
- Create: `src/auto_video/validation.py`
- Test: `tests/conftest.py`
- Test: `tests/test_project_loader.py`
- Modify: `tests/test_models_validation.py`

- [ ] **Step 1: Write project loader tests**

Create `tests/conftest.py`:

```python
from pathlib import Path

import pytest


@pytest.fixture
def demo_project_files(tmp_path: Path) -> Path:
    project = tmp_path / "demo"
    (project / "assets" / "refs").mkdir(parents=True)
    (project / "assets" / "refs" / "S01.txt").write_text("mock ref", encoding="utf-8")
    (project / "project.yaml").write_text(
        """
name: demo_ad
aspect_ratio: "9:16"
width: 1080
height: 1920
fps: 30
default_video_provider: mock
default_image_provider: mock
default_audio_provider: mock
render:
  transition:
    type: fade
    duration: 0.6
  bgm_volume: 0.2
""".strip(),
        encoding="utf-8",
    )
    (project / "shots.json").write_text(
        """
{
  "shots": [
    {
      "id": "S01",
      "title": "Hook",
      "duration": 5,
      "visual_prompt": "A tired person at a cold desk",
      "camera_motion": "slow_dolly_in",
      "environment_motion": "screen flicker",
      "performance": "tired breathing",
      "lighting": "cold fluorescent light",
      "audio_intent": "quiet room tone",
      "subtitle": "Late night again",
      "negative_prompt": "text, watermark",
      "refs": [
        {
          "path": "assets/refs/S01.txt",
          "type": "text",
          "role": "first_frame",
          "usage": "preserve_subject"
        }
      ]
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    return project
```

Create `tests/test_project_loader.py`:

```python
from pathlib import Path

import pytest

from auto_video.errors import AssetError, ConfigError
from auto_video.project import load_project, resolve_project_path


def test_load_project_reads_config_and_shots(demo_project_files):
    project = load_project(demo_project_files)
    assert project.config.name == "demo_ad"
    assert project.config.width == 1080
    assert project.shots[0].id == "S01"
    assert project.shots[0].refs[0].path == "assets/refs/S01.txt"


def test_resolve_project_path_rejects_escape(demo_project_files):
    with pytest.raises(AssetError) as exc:
        resolve_project_path(demo_project_files, "../secret.txt")
    assert "escapes project root" in str(exc.value)


def test_missing_shots_file_is_config_error(tmp_path: Path):
    project = tmp_path / "bad"
    project.mkdir()
    (project / "project.yaml").write_text("name: bad\n", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_project(project)
    assert "shots.json" in str(exc.value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /root/auto_ai_vedio
python3 -m pytest tests/test_project_loader.py -v
```

Expected: FAIL because `auto_video.project` does not exist.

- [ ] **Step 3: Implement project loading**

Create `src/auto_video/project.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .errors import AssetError, ConfigError
from .models import (
    AssetRef,
    Project,
    ProjectConfig,
    RenderConfig,
    RenderText,
    RenderTransition,
    ShotPlan,
)


def resolve_project_path(root: Path, value: str) -> Path:
    root = root.resolve()
    candidate = (root / value).resolve()
    if candidate != root and root not in candidate.parents:
        raise AssetError(
            f"path {value!r} escapes project root {root}",
            fix="Use a relative path inside the project directory.",
        )
    return candidate


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"missing {path.name}", fix=f"Create {path.name} in the project root.")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} must contain a mapping", fix="Use key/value YAML fields.")
    return data


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"missing {path.name}", fix=f"Create {path.name} in the project root.")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} must contain a JSON object", fix="Use an object with a shots array.")
    return data


def _render_config(data: dict[str, Any]) -> RenderConfig:
    render = data.get("render") or {}
    transition_data = render.get("transition") or {}
    brand_data = render.get("brand")
    cta_data = render.get("cta")
    return RenderConfig(
        transition=RenderTransition(
            type=str(transition_data.get("type", "fade")),
            duration=float(transition_data.get("duration", 0.6)),
        ),
        bgm=render.get("bgm"),
        bgm_volume=float(render.get("bgm_volume", 0.2)),
        subtitle_style=str(render.get("subtitle_style", "default")),
        brand=RenderText(text=str(brand_data["text"]), at=float(brand_data["at"])) if brand_data else None,
        cta=RenderText(text=str(cta_data["text"]), at=float(cta_data["at"])) if cta_data else None,
    )


def _project_config(root: Path, data: dict[str, Any]) -> ProjectConfig:
    name = data.get("name")
    if not name:
        raise ConfigError("project.yaml missing name", fix="Set a non-empty name field.")
    return ProjectConfig(
        name=str(name),
        root=root,
        aspect_ratio=str(data.get("aspect_ratio", "9:16")),
        width=int(data.get("width", 1080)),
        height=int(data.get("height", 1920)),
        fps=int(data.get("fps", 30)),
        default_video_provider=str(data.get("default_video_provider", "mock")),
        default_image_provider=str(data.get("default_image_provider", "mock")),
        default_audio_provider=str(data.get("default_audio_provider", "mock")),
        render=_render_config(data),
    )


def _shot_plan(raw: dict[str, Any]) -> ShotPlan:
    refs = tuple(AssetRef(**ref) for ref in raw.get("refs", []))
    return ShotPlan(
        id=str(raw["id"]),
        title=str(raw.get("title", "")),
        duration=float(raw["duration"]),
        intent=str(raw.get("intent", "")),
        provider=raw.get("provider"),
        visual_prompt=str(raw.get("visual_prompt", "")),
        camera_motion=str(raw.get("camera_motion", "")),
        environment_motion=str(raw.get("environment_motion", "")),
        performance=str(raw.get("performance", "")),
        lighting=str(raw.get("lighting", "")),
        audio_intent=str(raw.get("audio_intent", "")),
        subtitle=str(raw.get("subtitle", "")),
        negative_prompt=str(raw.get("negative_prompt", "")),
        refs=refs,
    )


def load_project(root: str | Path) -> Project:
    root = Path(root).resolve()
    config_data = _read_yaml(root / "project.yaml")
    shots_data = _read_json(root / "shots.json")
    shots_raw = shots_data.get("shots")
    if not isinstance(shots_raw, list) or not shots_raw:
        raise ConfigError("shots.json must contain a non-empty shots array", fix="Add at least one shot.")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    return Project(
        config=_project_config(root, config_data),
        shots=tuple(_shot_plan(raw) for raw in shots_raw),
        manifest=manifest,
    )
```

- [ ] **Step 4: Implement schema validation**

Create `src/auto_video/validation.py`:

```python
from __future__ import annotations

from .errors import AssetError, ConfigError
from .models import Project
from .project import resolve_project_path


def validate_project(project: Project) -> list[str]:
    warnings: list[str] = []
    seen: set[str] = set()
    if project.config.width <= 0 or project.config.height <= 0:
        raise ConfigError("width and height must be positive", fix="Set positive render dimensions.")
    if project.config.fps <= 0:
        raise ConfigError("fps must be positive", fix="Set fps to a positive integer.")
    for shot in project.shots:
        if shot.id in seen:
            raise ConfigError(f"duplicate shot id {shot.id}", fix="Use unique shot ids.")
        seen.add(shot.id)
        if not shot.visual_prompt and not shot.refs:
            raise ConfigError(
                f"shot {shot.id} needs visual_prompt or refs",
                fix="Add a visual_prompt or at least one reference asset.",
            )
        for index, ref in enumerate(shot.refs):
            path = resolve_project_path(project.config.root, ref.path)
            if not path.exists():
                raise AssetError(
                    f"shot {shot.id} refs[{index}].path not found: {ref.path}",
                    fix="Place the file at that path or update shots.json.",
                )
    return warnings
```

- [ ] **Step 5: Add validation test**

Append to `tests/test_models_validation.py`:

```python
from auto_video.project import load_project
from auto_video.validation import validate_project


def test_validate_project_accepts_demo_project(demo_project_files):
    project = load_project(demo_project_files)
    assert validate_project(project) == []
```

- [ ] **Step 6: Run loader and validation tests**

Run:

```bash
cd /root/auto_ai_vedio
python3 -m pytest tests/test_project_loader.py tests/test_models_validation.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/auto_video/project.py src/auto_video/validation.py tests/conftest.py tests/test_project_loader.py tests/test_models_validation.py
git commit -m "feat: load and validate video projects"
```

## Task 4: Manifest Registry

**Files:**
- Create: `src/auto_video/manifest.py`
- Test: `tests/test_manifest.py`

- [ ] **Step 1: Write failing manifest tests**

Create `tests/test_manifest.py`:

```python
import json
from pathlib import Path

from auto_video.manifest import ManifestStore
from auto_video.models import AssetResult


def test_manifest_updates_generated_clip(tmp_path: Path):
    store = ManifestStore(tmp_path / "manifest.json", project_name="demo")
    store.record_asset(AssetResult(shot_id="S01", provider="mock", path=tmp_path / "generated/clips/S01.mp4", kind="clip", duration=5.0))
    store.save()

    data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert data["project"] == "demo"
    assert data["shots"]["S01"]["clip"] == "generated/clips/S01.mp4"
    assert data["shots"]["S01"]["duration"] == 5.0
    assert data["shots"]["S01"]["status"] == "generated"


def test_manifest_records_failed_task(tmp_path: Path):
    store = ManifestStore(tmp_path / "manifest.json", project_name="demo")
    store.record_asset(AssetResult(shot_id="S03", provider="seedance", path=tmp_path / "generated/clips/S03.mp4", kind="clip", status="failed", error="SetLimitExceeded", retryable=True))
    store.save()

    data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert data["shots"]["S03"]["status"] == "failed"
    assert data["shots"]["S03"]["error"] == "SetLimitExceeded"
    assert data["shots"]["S03"]["retryable"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /root/auto_ai_vedio
python3 -m pytest tests/test_manifest.py -v
```

Expected: FAIL because `auto_video.manifest` does not exist.

- [ ] **Step 3: Implement manifest store**

Create `src/auto_video/manifest.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import AssetResult


class ManifestStore:
    def __init__(self, path: Path, *, project_name: str):
        self.path = path
        self.root = path.parent.resolve()
        if path.exists():
            self.data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.data = {"project": project_name, "schema_version": "0.1", "assets": {}, "shots": {}, "renders": {}}
        self.data.setdefault("project", project_name)
        self.data.setdefault("schema_version", "0.1")
        self.data.setdefault("assets", {})
        self.data.setdefault("shots", {})
        self.data.setdefault("renders", {})

    def _relative(self, value: Path) -> str:
        try:
            return value.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return value.as_posix()

    def record_asset(self, result: AssetResult) -> None:
        shot = self.data["shots"].setdefault(result.shot_id, {})
        shot["status"] = result.status
        shot["provider"] = result.provider
        if result.kind == "image":
            shot["image"] = self._relative(result.path)
        elif result.kind == "clip":
            shot["clip"] = self._relative(result.path)
        elif result.kind == "audio":
            shot["audio"] = self._relative(result.path)
        else:
            self.data["assets"][f"{result.shot_id}:{result.kind}"] = self._relative(result.path)
        if result.duration is not None:
            shot["duration"] = result.duration
        if result.error is not None:
            shot["error"] = result.error
        if result.retryable:
            shot["retryable"] = True

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run manifest tests**

Run:

```bash
cd /root/auto_ai_vedio
python3 -m pytest tests/test_manifest.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/auto_video/manifest.py tests/test_manifest.py
git commit -m "feat: add manifest registry"
```

## Task 5: Prompt Planner

**Files:**
- Create: `src/auto_video/prompts.py`
- Test: `tests/test_prompts.py`

- [ ] **Step 1: Write failing prompt tests**

Create `tests/test_prompts.py`:

```python
from auto_video.project import load_project
from auto_video.prompts import plan_prompt


def test_wan_prompt_prioritizes_motion_fields(demo_project_files):
    project = load_project(demo_project_files)
    prompt = plan_prompt(project.shots[0], provider="wan")
    assert "A tired person at a cold desk" in prompt
    assert "Camera: slow_dolly_in" in prompt
    assert "Environment motion: screen flicker" in prompt
    assert "Negative: text, watermark" in prompt


def test_seedance_prompt_includes_reference_usage(demo_project_files):
    project = load_project(demo_project_files)
    prompt = plan_prompt(project.shots[0], provider="seedance")
    assert "Shot S01" in prompt
    assert "Duration: 5.0s" in prompt
    assert "first_frame" in prompt
    assert "preserve_subject" in prompt
    assert "Audio intent: quiet room tone" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /root/auto_ai_vedio
python3 -m pytest tests/test_prompts.py -v
```

Expected: FAIL because `auto_video.prompts` does not exist.

- [ ] **Step 3: Implement prompt planner**

Create `src/auto_video/prompts.py`:

```python
from __future__ import annotations

from .models import ShotPlan


def _reference_lines(shot: ShotPlan) -> list[str]:
    return [
        f"- {ref.type} {ref.path}: role={ref.role}, usage={ref.usage}"
        for ref in shot.refs
    ]


def _base_lines(shot: ShotPlan) -> list[str]:
    return [
        f"Visual intent: {shot.visual_prompt}",
        f"Performance: {shot.performance}",
        f"Camera: {shot.camera_motion}",
        f"Environment motion: {shot.environment_motion}",
        f"Lighting: {shot.lighting}",
        f"Audio intent: {shot.audio_intent}",
        f"Negative: {shot.negative_prompt}",
    ]


def plan_prompt(shot: ShotPlan, *, provider: str) -> str:
    if provider == "seedance":
        parts = [
            f"Shot {shot.id}: {shot.title or shot.intent}",
            f"Duration: {shot.duration}s",
            "Director controls:",
            *_base_lines(shot),
            "References:",
            *_reference_lines(shot),
            "Generate a coherent 4-15 second multimodal video shot with clear subject motion, camera motion, environment motion, and audio-video timing.",
        ]
        return "\n".join(line for line in parts if line)
    if provider == "wan":
        parts = [
            shot.visual_prompt,
            f"Performance: {shot.performance}",
            f"Camera: {shot.camera_motion}",
            f"Environment motion: {shot.environment_motion}",
            f"Lighting: {shot.lighting}",
            "continuous smooth cinematic motion, no text, no watermark",
            f"Negative: {shot.negative_prompt}",
        ]
        return "\n".join(line for line in parts if line)
    if provider == "mock":
        return f"MOCK {shot.id}: {shot.visual_prompt} ({shot.duration}s)"
    return "\n".join(line for line in _base_lines(shot) if line)
```

- [ ] **Step 4: Run prompt tests**

Run:

```bash
cd /root/auto_ai_vedio
python3 -m pytest tests/test_prompts.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/auto_video/prompts.py tests/test_prompts.py
git commit -m "feat: add provider prompt planner"
```

## Task 6: Mock Provider And Generation Pipeline

**Files:**
- Create: `src/auto_video/providers/__init__.py`
- Create: `src/auto_video/providers/base.py`
- Create: `src/auto_video/providers/mock.py`
- Create: `src/auto_video/pipeline.py`
- Test: `tests/test_mock_pipeline.py`

- [ ] **Step 1: Write failing pipeline tests**

Create `tests/test_mock_pipeline.py`:

```python
from pathlib import Path

from auto_video.pipeline import generate_images, generate_videos
from auto_video.project import load_project


def test_images_dry_run_does_not_write_manifest(demo_project_files):
    project = load_project(demo_project_files)
    plan = generate_images(project, provider_name="mock", dry_run=True)
    assert plan["dry_run"] is True
    assert plan["planned"][0]["shot_id"] == "S01"
    assert not (demo_project_files / "manifest.json").exists()


def test_mock_video_generation_writes_clip_and_manifest(demo_project_files):
    project = load_project(demo_project_files)
    results = generate_videos(project, provider_name="mock", dry_run=False)
    clip = demo_project_files / "generated" / "clips" / "S01.mp4"
    manifest = demo_project_files / "manifest.json"
    assert results[0].path == clip
    assert clip.read_text(encoding="utf-8").startswith("mock video")
    assert '"clip": "generated/clips/S01.mp4"' in manifest.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /root/auto_ai_vedio
python3 -m pytest tests/test_mock_pipeline.py -v
```

Expected: FAIL because `auto_video.pipeline` does not exist.

- [ ] **Step 3: Implement provider interfaces**

Create `src/auto_video/providers/base.py`:

```python
from __future__ import annotations

from typing import Protocol

from auto_video.models import AssetResult, GenerationTask


class ImageProvider(Protocol):
    name: str

    def generate_image(self, task: GenerationTask) -> AssetResult:
        ...


class VideoProvider(Protocol):
    name: str

    def generate_video(self, task: GenerationTask) -> AssetResult:
        ...
```

Create `src/auto_video/providers/mock.py`:

```python
from __future__ import annotations

from auto_video.models import AssetResult, GenerationTask


class MockProvider:
    name = "mock"

    def generate_image(self, task: GenerationTask) -> AssetResult:
        task.output_path.parent.mkdir(parents=True, exist_ok=True)
        task.output_path.write_text(f"mock image for {task.shot.id}\n{task.prompt}\n", encoding="utf-8")
        return AssetResult(shot_id=task.shot.id, provider=self.name, path=task.output_path, kind="image")

    def generate_video(self, task: GenerationTask) -> AssetResult:
        task.output_path.parent.mkdir(parents=True, exist_ok=True)
        task.output_path.write_text(f"mock video for {task.shot.id}\n{task.prompt}\n", encoding="utf-8")
        return AssetResult(shot_id=task.shot.id, provider=self.name, path=task.output_path, kind="clip", duration=task.shot.duration)
```

Create `src/auto_video/providers/__init__.py`:

```python
from __future__ import annotations

from .mock import MockProvider


def get_provider(name: str):
    if name == "mock":
        return MockProvider()
    raise KeyError(f"provider {name!r} is not available in this build")
```

- [ ] **Step 4: Implement generation pipeline**

Create `src/auto_video/pipeline.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from .manifest import ManifestStore
from .models import AssetResult, GenerationTask, Project
from .prompts import plan_prompt
from .providers import get_provider


def _select_shots(project: Project, only: set[str] | None = None):
    for shot in project.shots:
        if only and shot.id not in only:
            continue
        yield shot


def generate_images(project: Project, *, provider_name: str | None = None, dry_run: bool = False, only: set[str] | None = None) -> dict[str, Any] | list[AssetResult]:
    provider_name = provider_name or project.config.default_image_provider
    provider = get_provider(provider_name)
    planned: list[dict[str, str]] = []
    results: list[AssetResult] = []
    store = ManifestStore(project.config.root / "manifest.json", project_name=project.config.name)
    for shot in _select_shots(project, only):
        output = project.config.root / "generated" / "images" / f"{shot.id}.txt"
        prompt = plan_prompt(shot, provider=provider_name)
        if dry_run:
            planned.append({"shot_id": shot.id, "provider": provider_name, "output": output.as_posix()})
            continue
        result = provider.generate_image(GenerationTask(project.config, shot, prompt, output, dry_run=False))
        store.record_asset(result)
        results.append(result)
    if dry_run:
        return {"dry_run": True, "planned": planned}
    store.save()
    return results


def generate_videos(project: Project, *, provider_name: str | None = None, dry_run: bool = False, only: set[str] | None = None) -> dict[str, Any] | list[AssetResult]:
    provider_name = provider_name or project.config.default_video_provider
    provider = get_provider(provider_name)
    planned: list[dict[str, str]] = []
    results: list[AssetResult] = []
    store = ManifestStore(project.config.root / "manifest.json", project_name=project.config.name)
    for shot in _select_shots(project, only):
        output = project.config.root / "generated" / "clips" / f"{shot.id}.mp4"
        prompt = plan_prompt(shot, provider=provider_name)
        if dry_run:
            planned.append({"shot_id": shot.id, "provider": provider_name, "output": output.as_posix()})
            continue
        result = provider.generate_video(GenerationTask(project.config, shot, prompt, output, dry_run=False))
        store.record_asset(result)
        results.append(result)
    if dry_run:
        return {"dry_run": True, "planned": planned}
    store.save()
    return results
```

- [ ] **Step 5: Run pipeline tests**

Run:

```bash
cd /root/auto_ai_vedio
python3 -m pytest tests/test_mock_pipeline.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/auto_video/providers src/auto_video/pipeline.py tests/test_mock_pipeline.py
git commit -m "feat: add mock generation pipeline"
```

## Task 7: Render Planning And Probe Reports

**Files:**
- Create: `src/auto_video/render.py`
- Create: `src/auto_video/probe.py`
- Test: `tests/test_render_probe.py`

- [ ] **Step 1: Write failing render and probe tests**

Create `tests/test_render_probe.py`:

```python
from auto_video.pipeline import generate_videos
from auto_video.project import load_project
from auto_video.probe import probe_project
from auto_video.render import build_render_plan


def test_render_plan_uses_manifest_clip(demo_project_files):
    project = load_project(demo_project_files)
    generate_videos(project, provider_name="mock", dry_run=False)
    project = load_project(demo_project_files)

    plan = build_render_plan(project)
    assert plan["output"] == "renders/final.mp4"
    assert plan["shots"][0]["id"] == "S01"
    assert plan["shots"][0]["clip"] == "generated/clips/S01.mp4"
    assert plan["ffmpeg"][0] == "ffmpeg"


def test_probe_reports_missing_or_mock_duration(demo_project_files):
    project = load_project(demo_project_files)
    generate_videos(project, provider_name="mock", dry_run=False)
    project = load_project(demo_project_files)

    report = probe_project(project, dry_run=True)
    assert report["dry_run"] is True
    assert report["shots"][0]["id"] == "S01"
    assert report["shots"][0]["manifest_duration"] == 5.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /root/auto_ai_vedio
python3 -m pytest tests/test_render_probe.py -v
```

Expected: FAIL because `auto_video.render` and `auto_video.probe` do not exist.

- [ ] **Step 3: Implement render planning**

Create `src/auto_video/render.py`:

```python
from __future__ import annotations

from .errors import RenderError
from .models import Project


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
        shots.append({"id": shot.id, "clip": clip, "duration": shot.duration, "subtitle": shot.subtitle})
    output = "renders/final.mp4"
    ffmpeg = ["ffmpeg", "-y"]
    for item in shots:
        ffmpeg.extend(["-i", item["clip"]])
    ffmpeg.extend(["-filter_complex", "xfade-and-subtitle-plan", output])
    return {
        "output": output,
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
```

- [ ] **Step 4: Implement probe reporting**

Create `src/auto_video/probe.py`:

```python
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
```

- [ ] **Step 5: Run render/probe tests**

Run:

```bash
cd /root/auto_ai_vedio
python3 -m pytest tests/test_render_probe.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/auto_video/render.py src/auto_video/probe.py tests/test_render_probe.py
git commit -m "feat: add render planning and probe reports"
```

## Task 8: CLI Commands And Init Workflow

**Files:**
- Modify: `src/auto_video/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Replace CLI tests with command behavior tests**

Replace `tests/test_cli.py` with:

```python
from pathlib import Path

from auto_video.cli import main


def test_cli_help_exits_successfully(capsys):
    code = main(["--help"])
    captured = capsys.readouterr()
    assert code == 0
    assert "auto-video" in captured.out
    assert "validate" in captured.out


def test_cli_init_creates_project(tmp_path: Path):
    project = tmp_path / "demo"
    code = main(["init", str(project)])
    assert code == 0
    assert (project / "project.yaml").exists()
    assert (project / "shots.json").exists()
    assert (project / "assets" / "refs" / "S01.txt").exists()


def test_cli_validate_and_dry_run_generation(tmp_path: Path):
    project = tmp_path / "demo"
    assert main(["init", str(project)]) == 0
    assert main(["validate", str(project)]) == 0
    assert main(["images", str(project), "--dry-run"]) == 0
    assert main(["generate", str(project), "--dry-run"]) == 0
    assert not (project / "manifest.json").exists()


def test_cli_mock_generate_then_probe(tmp_path: Path):
    project = tmp_path / "demo"
    assert main(["init", str(project)]) == 0
    assert main(["generate", str(project), "--provider", "mock"]) == 0
    assert (project / "manifest.json").exists()
    assert main(["probe", str(project), "--dry-run"]) == 0
```

- [ ] **Step 2: Run CLI tests to verify they fail**

Run:

```bash
cd /root/auto_ai_vedio
python3 -m pytest tests/test_cli.py -v
```

Expected: FAIL because command handlers are not implemented.

- [ ] **Step 3: Implement CLI command handlers**

Replace `src/auto_video/cli.py` with:

```python
from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .errors import AutoVideoError
from .pipeline import generate_images, generate_videos
from .probe import probe_project
from .project import load_project
from .render import build_render_plan
from .validation import validate_project


PROJECT_YAML = """name: demo_ad
aspect_ratio: "9:16"
width: 1080
height: 1920
fps: 30
default_video_provider: mock
default_image_provider: mock
default_audio_provider: mock
render:
  transition:
    type: fade
    duration: 0.6
  bgm_volume: 0.2
  subtitle_style: default
  brand:
    text: "Demo Brand"
    at: 1.2
  cta:
    text: "Click for more"
    at: 2.6
"""

SHOTS_JSON = """{
  "shots": [
    {
      "id": "S01",
      "title": "Hook",
      "duration": 5,
      "intent": "Show fatigue and introduce the product need",
      "provider": "mock",
      "visual_prompt": "A tired person at a cold desk",
      "camera_motion": "slow_dolly_in",
      "environment_motion": "screen flicker, dust floats",
      "performance": "tired breathing, shoulders drop slightly",
      "lighting": "cold fluorescent light",
      "audio_intent": "quiet room tone",
      "subtitle": "Late night again",
      "negative_prompt": "text, watermark",
      "refs": [
        {
          "path": "assets/refs/S01.txt",
          "type": "text",
          "role": "first_frame",
          "usage": "preserve_subject"
        }
      ]
    }
  ]
}
"""


def _csv(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {item.strip() for item in value.split(",") if item.strip()}


def init_project(path: Path) -> None:
    (path / "assets" / "refs").mkdir(parents=True, exist_ok=True)
    (path / "generated" / "images").mkdir(parents=True, exist_ok=True)
    (path / "generated" / "clips").mkdir(parents=True, exist_ok=True)
    (path / "generated" / "audio").mkdir(parents=True, exist_ok=True)
    (path / "renders").mkdir(parents=True, exist_ok=True)
    (path / "reports").mkdir(parents=True, exist_ok=True)
    (path / "project.yaml").write_text(PROJECT_YAML, encoding="utf-8")
    (path / "shots.json").write_text(SHOTS_JSON, encoding="utf-8")
    (path / "assets" / "refs" / "S01.txt").write_text("mock first-frame reference\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="auto-video")
    sub = parser.add_subparsers(dest="command", required=False)

    init = sub.add_parser("init")
    init.add_argument("project")

    validate = sub.add_parser("validate")
    validate.add_argument("project")

    images = sub.add_parser("images")
    images.add_argument("project")
    images.add_argument("--dry-run", action="store_true")
    images.add_argument("--provider")
    images.add_argument("--only")

    generate = sub.add_parser("generate")
    generate.add_argument("project")
    generate.add_argument("--dry-run", action="store_true")
    generate.add_argument("--provider")
    generate.add_argument("--only")

    assemble = sub.add_parser("assemble")
    assemble.add_argument("project")
    assemble.add_argument("--dry-run", action="store_true")

    probe = sub.add_parser("probe")
    probe.add_argument("project")
    probe.add_argument("--dry-run", action="store_true")

    providers = sub.add_parser("providers")
    providers_sub = providers.add_subparsers(dest="providers_command")
    providers_sub.add_parser("health")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command is None:
            parser.print_help()
            return 0
        if args.command == "init":
            init_project(Path(args.project))
            return 0
        if args.command == "validate":
            validate_project(load_project(args.project))
            return 0
        if args.command == "images":
            result = generate_images(load_project(args.project), provider_name=args.provider, dry_run=args.dry_run, only=_csv(args.only))
            if args.dry_run:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "generate":
            result = generate_videos(load_project(args.project), provider_name=args.provider, dry_run=args.dry_run, only=_csv(args.only))
            if args.dry_run:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "assemble":
            plan = build_render_plan(load_project(args.project))
            if args.dry_run:
                print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0
        if args.command == "probe":
            report = probe_project(load_project(args.project), dry_run=args.dry_run)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        if args.command == "providers" and args.providers_command == "health":
            print(json.dumps({"mock": "ok"}, indent=2))
            return 0
        parser.print_help()
        return 2
    except AutoVideoError as exc:
        print(str(exc))
        return 1


def entrypoint() -> int:
    return main()
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
cd /root/auto_ai_vedio
python3 -m pytest tests/test_cli.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/auto_video/cli.py tests/test_cli.py
git commit -m "feat: wire CLI commands"
```

## Task 9: Example Project And Documentation

**Files:**
- Create: `examples/demo_project/project.yaml`
- Create: `examples/demo_project/shots.json`
- Create: `examples/demo_project/assets/refs/S01.txt`
- Modify: `README.md`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Add failing example smoke test**

Append to `tests/test_cli.py`:

```python
def test_checked_in_example_validates():
    assert main(["validate", "examples/demo_project"]) == 0
    assert main(["images", "examples/demo_project", "--dry-run"]) == 0
    assert main(["generate", "examples/demo_project", "--dry-run"]) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /root/auto_ai_vedio
python3 -m pytest tests/test_cli.py::test_checked_in_example_validates -v
```

Expected: FAIL because `examples/demo_project` does not exist.

- [ ] **Step 3: Create checked-in example project**

Create `examples/demo_project/project.yaml`:

```yaml
name: demo_ad
aspect_ratio: "9:16"
width: 1080
height: 1920
fps: 30
default_video_provider: mock
default_image_provider: mock
default_audio_provider: mock
render:
  transition:
    type: fade
    duration: 0.6
  bgm_volume: 0.2
  subtitle_style: default
  brand:
    text: "Demo Brand"
    at: 1.2
  cta:
    text: "Click for more"
    at: 2.6
```

Create `examples/demo_project/shots.json`:

```json
{
  "shots": [
    {
      "id": "S01",
      "title": "Hook",
      "duration": 5,
      "intent": "Show fatigue and introduce the product need",
      "provider": "mock",
      "visual_prompt": "A tired person at a cold desk",
      "camera_motion": "slow_dolly_in",
      "environment_motion": "screen flicker, dust floats",
      "performance": "tired breathing, shoulders drop slightly",
      "lighting": "cold fluorescent light",
      "audio_intent": "quiet room tone",
      "subtitle": "Late night again",
      "negative_prompt": "text, watermark",
      "refs": [
        {
          "path": "assets/refs/S01.txt",
          "type": "text",
          "role": "first_frame",
          "usage": "preserve_subject"
        }
      ]
    }
  ]
}
```

Create `examples/demo_project/assets/refs/S01.txt`:

```text
Mock first-frame reference for S01.
```

- [ ] **Step 4: Expand README with workflow and migration notes**

Replace `README.md` with:

```markdown
# auto_ai_vedio

Seedance-inspired AI video production CLI pipeline.

## MVP workflow

```bash
python3 -m auto_video init demo_project
python3 -m auto_video validate demo_project
python3 -m auto_video images demo_project --dry-run
python3 -m auto_video generate demo_project --dry-run
python3 -m auto_video generate demo_project --provider mock
python3 -m auto_video assemble demo_project --dry-run
python3 -m auto_video probe demo_project --dry-run
```

## Design

See `docs/superpowers/specs/2026-06-26-ai-video-cli-pipeline-design.md`.

## Prototype migration

The old `/root/ai_vedio` project maps into this MVP as follows:

- `batch_plans/*.json` becomes `shots.json`.
- `edl/*.json` becomes render settings plus manifest-derived EDL.
- `tools/providers/*.py` becomes provider adapters.
- `tools/assemble2.py` becomes `src/auto_video/render.py`.
- production SOP documents become validation, probe, and README guidance.

Default tests use the mock provider and do not require API keys, network, cloud GPU, or large video files.
```

- [ ] **Step 5: Run example tests**

Run:

```bash
cd /root/auto_ai_vedio
python3 -m pytest tests/test_cli.py::test_checked_in_example_validates -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add examples/demo_project README.md tests/test_cli.py
git commit -m "docs: add demo project workflow"
```

## Task 10: Full Verification And Remote Sync

**Files:**
- No source file changes expected unless verification exposes an issue.

- [ ] **Step 1: Run the full test suite**

Run:

```bash
cd /root/auto_ai_vedio
python3 -m pytest -v
```

Expected: all tests PASS.

- [ ] **Step 2: Run CLI smoke commands**

Run:

```bash
cd /root/auto_ai_vedio
tmpdir="$(mktemp -d)"
python3 -m auto_video init "$tmpdir/demo"
python3 -m auto_video validate "$tmpdir/demo"
python3 -m auto_video images "$tmpdir/demo" --dry-run
python3 -m auto_video generate "$tmpdir/demo" --dry-run
python3 -m auto_video generate "$tmpdir/demo" --provider mock
python3 -m auto_video assemble "$tmpdir/demo" --dry-run
python3 -m auto_video probe "$tmpdir/demo" --dry-run
```

Expected:

- `validate` exits 0.
- dry-run commands print JSON plans and do not create `manifest.json`.
- mock generation creates `manifest.json` and `generated/clips/S01.mp4`.
- assemble dry-run prints a JSON render plan.
- probe dry-run prints a JSON report.

- [ ] **Step 3: Check git status**

Run:

```bash
cd /root/auto_ai_vedio
git status --short --branch
```

Expected: clean working tree on `main`.

- [ ] **Step 4: Push to GitHub**

Run:

```bash
cd /root/auto_ai_vedio
git push
```

Expected: local `main` is pushed to `origin/main`.

## Self-Review

Spec coverage:

- Project initialization is covered by Task 8 and Task 9.
- Validation is covered by Task 3 and CLI wiring in Task 8.
- Manifest behavior is covered by Task 4 and Task 6.
- Prompt planning is covered by Task 5.
- Mock provider and default offline tests are covered by Task 6.
- Render dry-run planning is covered by Task 7 and Task 8.
- Probe reporting is covered by Task 7.
- Example workflow and prototype migration notes are covered by Task 9.
- Full verification and remote sync are covered by Task 10.

No intentional gaps remain for the MVP described in the design spec. Real Seedance, Seedream, Wan, cloud GPU worker, Web UI, and HyperFrames renderer remain outside this implementation plan.
