# SSH Remote Worker Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a vendor-neutral SSH/rsync remote worker path that exports a bundle, runs `auto-video worker run` on a remote host, downloads results, and imports them locally.

**Architecture:** Create a focused `remote_transport` module for command planning, safety checks, command execution, and orchestration. CLI integration stays thin: `auto-video remote run` parses options, calls `run_remote_worker()`, and prints JSON. Tests stay offline by using fake command runners that copy bundles through temp directories and invoke the existing local `run_worker_bundle()`.

**Tech Stack:** Python 3.12, dataclasses, pathlib, subprocess, tempfile, shutil, argparse, pytest, existing `worker_bundle` and `worker_runner` modules.

---

## File Map

- Create `src/auto_video/remote_transport.py`: remote run option dataclasses, plan dataclasses, SSH/rsync command planning, safety checks, subprocess runner, orchestration.
- Modify `src/auto_video/cli.py`: add `remote run` parser and command handling.
- Modify `README.md`: document SSH/rsync remote worker flow and remote host prerequisites.
- Test with `tests/test_remote_transport.py` and `tests/test_remote_cli.py`.

## Task 1: Remote Command Planner

**Files:**
- Create: `src/auto_video/remote_transport.py`
- Test: `tests/test_remote_transport.py`

- [ ] **Step 1: Write failing planner tests**

Create `tests/test_remote_transport.py`:

```python
from pathlib import Path

import pytest

from auto_video.errors import ConfigError
from auto_video.project import load_project
from auto_video.remote_transport import RemoteRunOptions, build_remote_run_plan


def test_build_remote_run_plan_includes_upload_run_and_download_commands(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    local_dir = tmp_path / "remote-work"

    plan = build_remote_run_plan(
        project,
        RemoteRunOptions(
            host="gpu-box",
            remote_dir="/data/auto-video/jobs/demo",
            local_dir=local_dir,
            remote_auto_video="/opt/auto-video",
            ssh_options=("StrictHostKeyChecking=no",),
            rsync_options=("--info=progress2",),
        ),
    )

    assert plan.project_root == demo_project_files.resolve()
    assert plan.local_dir == local_dir
    assert plan.local_bundle == local_dir / "bundle"
    assert plan.host == "gpu-box"
    assert plan.remote_dir == "/data/auto-video/jobs/demo"
    assert list(plan.upload) == [
        "rsync",
        "-az",
        "--info=progress2",
        "--delete",
        f"{(local_dir / 'bundle').as_posix()}/",
        "gpu-box:/data/auto-video/jobs/demo/",
    ]
    assert list(plan.run) == [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "gpu-box",
        "/opt/auto-video",
        "worker",
        "run",
        "/data/auto-video/jobs/demo",
    ]
    assert list(plan.download) == [
        "rsync",
        "-az",
        "--info=progress2",
        "--delete",
        "gpu-box:/data/auto-video/jobs/demo/",
        f"{(local_dir / 'bundle').as_posix()}/",
    ]


def test_build_remote_run_plan_uses_safe_default_local_dir(demo_project_files):
    project = load_project(demo_project_files)

    plan = build_remote_run_plan(
        project,
        RemoteRunOptions(host="gpu-box", remote_dir="/data/auto-video/jobs/demo"),
    )

    assert plan.local_bundle.name == "bundle"
    assert "auto-video-remote" in plan.local_bundle.as_posix()
    assert demo_project_files.resolve() not in plan.local_bundle.resolve().parents


def test_build_remote_run_plan_rejects_unsafe_host(demo_project_files, tmp_path):
    project = load_project(demo_project_files)

    with pytest.raises(ConfigError) as exc:
        build_remote_run_plan(
            project,
            RemoteRunOptions(host="bad host", remote_dir="/data/demo", local_dir=tmp_path / "work"),
        )

    assert "host" in str(exc.value)


def test_build_remote_run_plan_rejects_unsafe_remote_dir(demo_project_files, tmp_path):
    project = load_project(demo_project_files)

    with pytest.raises(ConfigError) as exc:
        build_remote_run_plan(
            project,
            RemoteRunOptions(host="gpu-box", remote_dir="relative/demo", local_dir=tmp_path / "work"),
        )

    assert "remote-dir" in str(exc.value)

    with pytest.raises(ConfigError) as control_exc:
        build_remote_run_plan(
            project,
            RemoteRunOptions(host="gpu-box", remote_dir="/data/demo;rm", local_dir=tmp_path / "work"),
        )

    assert "remote-dir" in str(control_exc.value)


def test_build_remote_run_plan_rejects_local_dir_inside_project(demo_project_files):
    project = load_project(demo_project_files)

    with pytest.raises(ConfigError) as exc:
        build_remote_run_plan(
            project,
            RemoteRunOptions(host="gpu-box", remote_dir="/data/demo", local_dir=demo_project_files / "remote-work"),
        )

    assert "project root" in str(exc.value)
```

- [ ] **Step 2: Run planner tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_remote_transport.py -v
```

Expected: FAIL during collection because `auto_video.remote_transport` does not exist.

- [ ] **Step 3: Implement remote command planning**

Create `src/auto_video/remote_transport.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence
import subprocess
import tempfile

from .errors import ConfigError, ProviderError
from .jobs import utc_now_iso
from .models import Project

UNSAFE_TOKEN_CHARS = set("\n\r\0;&|`$<>")


@dataclass(frozen=True)
class RemoteRunOptions:
    host: str
    remote_dir: str
    provider_name: str | None = None
    kind: str = "video"
    only: set[str] | None = None
    local_dir: Path | None = None
    remote_auto_video: str = "auto-video"
    ssh_options: tuple[str, ...] = ()
    rsync_options: tuple[str, ...] = ()


@dataclass(frozen=True)
class RemoteRunPlan:
    project_root: Path
    local_dir: Path
    local_bundle: Path
    host: str
    remote_dir: str
    upload: tuple[str, ...]
    run: tuple[str, ...]
    download: tuple[str, ...]

    def commands_dict(self) -> dict[str, list[str]]:
        return {
            "upload": list(self.upload),
            "run": list(self.run),
            "download": list(self.download),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_root": self.project_root.as_posix(),
            "local_dir": self.local_dir.as_posix(),
            "local_bundle": self.local_bundle.as_posix(),
            "host": self.host,
            "remote_dir": self.remote_dir,
            "commands": self.commands_dict(),
        }


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    def run(self, command: Sequence[str]) -> CommandResult:
        """Run one command and raise a user-facing error on failure."""


class SubprocessCommandRunner:
    def run(self, command: Sequence[str]) -> CommandResult:
        try:
            completed = subprocess.run(list(command), check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise ConfigError(
                f"missing command {command[0]!r}",
                fix="Install the required command locally or adjust your PATH.",
            ) from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise ProviderError(
                f"remote transport command failed: {' '.join(command[:3])}",
                fix=stderr or "Check SSH access, rsync installation, and remote auto-video setup.",
            ) from exc
        return CommandResult(
            command=tuple(command),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def _reject_unsafe_token(name: str, value: str, *, reject_whitespace: bool = True) -> None:
    if not value:
        raise ConfigError(f"{name} cannot be empty", fix=f"Pass a non-empty {name} value.")
    if reject_whitespace and any(char.isspace() for char in value):
        raise ConfigError(f"{name} contains whitespace", fix=f"Use a {name} value without spaces.")
    if any(char in UNSAFE_TOKEN_CHARS for char in value):
        raise ConfigError(f"{name} contains unsafe shell control characters", fix=f"Use a plain {name} value.")


def _validate_host(host: str) -> None:
    _reject_unsafe_token("host", host)


def _validate_remote_dir(remote_dir: str) -> None:
    _reject_unsafe_token("remote-dir", remote_dir)
    if not remote_dir.startswith("/"):
        raise ConfigError("remote-dir must be an absolute path", fix="Use a Unix path beginning with '/'.")


def _validate_command_token(name: str, value: str) -> None:
    _reject_unsafe_token(name, value)


def _validate_option_values(name: str, values: tuple[str, ...]) -> None:
    for value in values:
        _reject_unsafe_token(name, value)


def _safe_project_name(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value).strip("_")
    return safe or "project"


def _default_local_dir(project_name: str) -> Path:
    stamp = utc_now_iso().replace("-", "").replace(":", "").replace("T", "_").replace("Z", "")
    return Path(tempfile.gettempdir()) / "auto-video-remote" / f"{_safe_project_name(project_name)}_{stamp}"


def _ensure_local_dir_outside_project(project_root: Path, local_bundle: Path) -> None:
    project_root = project_root.resolve()
    local_bundle = local_bundle.resolve()
    if local_bundle == project_root or project_root in local_bundle.parents:
        raise ConfigError(
            "local remote work directory cannot be inside the project root",
            fix="Choose a --local-dir outside the project so bundle export cannot remove project files.",
        )


def _with_trailing_slash(value: str) -> str:
    return value.rstrip("/") + "/"


def _ssh_option_args(options: tuple[str, ...]) -> list[str]:
    args: list[str] = []
    for option in options:
        args.extend(["-o", option])
    return args


def build_remote_run_plan(project: Project, options: RemoteRunOptions) -> RemoteRunPlan:
    _validate_host(options.host)
    _validate_remote_dir(options.remote_dir)
    _validate_command_token("remote-auto-video", options.remote_auto_video)
    _validate_option_values("ssh-option", options.ssh_options)
    _validate_option_values("rsync-option", options.rsync_options)

    local_dir = options.local_dir or _default_local_dir(project.config.name)
    local_bundle = local_dir / "bundle"
    _ensure_local_dir_outside_project(project.config.root, local_bundle)

    remote_dir = options.remote_dir.rstrip("/") or "/"
    remote_spec = f"{options.host}:{_with_trailing_slash(remote_dir)}"
    local_spec = _with_trailing_slash(local_bundle.as_posix())
    rsync_prefix = ("rsync", "-az", *options.rsync_options, "--delete")
    upload = (*rsync_prefix, local_spec, remote_spec)
    download = (*rsync_prefix, remote_spec, local_spec)
    run = (
        "ssh",
        *_ssh_option_args(options.ssh_options),
        options.host,
        options.remote_auto_video,
        "worker",
        "run",
        remote_dir,
    )
    return RemoteRunPlan(
        project_root=project.config.root.resolve(),
        local_dir=local_dir,
        local_bundle=local_bundle,
        host=options.host,
        remote_dir=remote_dir,
        upload=tuple(upload),
        run=tuple(run),
        download=tuple(download),
    )
```

- [ ] **Step 4: Run planner tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_remote_transport.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/auto_video/remote_transport.py tests/test_remote_transport.py
git commit -m "feat: plan ssh remote worker commands"
```

## Task 2: Remote Worker Orchestration

**Files:**
- Modify: `src/auto_video/remote_transport.py`
- Modify: `tests/test_remote_transport.py`

- [ ] **Step 1: Add failing orchestration tests**

Append to `tests/test_remote_transport.py`:

```python
import shutil

from auto_video.errors import ProviderError
from auto_video.remote_transport import CommandResult, run_remote_worker
from auto_video.worker_runner import run_worker_bundle


class FakeRemoteRunner:
    def __init__(self, remote_bundle: Path):
        self.remote_bundle = remote_bundle
        self.commands: list[tuple[str, ...]] = []

    def run(self, command):
        command = tuple(command)
        self.commands.append(command)
        if len(self.commands) == 1:
            source = Path(command[-2])
            shutil.copytree(source, self.remote_bundle, dirs_exist_ok=True)
        elif len(self.commands) == 2:
            run_worker_bundle(self.remote_bundle)
        elif len(self.commands) == 3:
            destination = Path(command[-1])
            shutil.copytree(self.remote_bundle, destination, dirs_exist_ok=True)
        return CommandResult(command=command)


class FailingUploadRunner:
    def __init__(self):
        self.commands: list[tuple[str, ...]] = []

    def run(self, command):
        self.commands.append(tuple(command))
        raise ProviderError("upload failed")


def test_run_remote_worker_exports_runs_downloads_and_imports(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    remote_bundle = tmp_path / "fake-remote-bundle"
    runner = FakeRemoteRunner(remote_bundle)

    summary = run_remote_worker(
        project,
        RemoteRunOptions(
            host="fake-gpu",
            remote_dir="/tmp/remote-bundle",
            local_dir=tmp_path / "local-run",
            provider_name="mock",
            kind="video",
        ),
        runner=runner,
    )

    assert [command[0] for command in runner.commands] == ["rsync", "ssh", "rsync"]
    assert summary["dry_run"] is False
    assert summary["project"] == "demo_ad"
    assert summary["imported"] == ["demo_ad:S01:video:mock"]
    assert summary["failed"] == []
    assert (demo_project_files / "manifest.json").exists()
    assert (demo_project_files / "generated" / "clips" / "S01.mp4").exists()
    assert (remote_bundle / "result.json").exists()


def test_run_remote_worker_dry_run_does_not_export_or_import(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    runner = FakeRemoteRunner(tmp_path / "remote")

    summary = run_remote_worker(
        project,
        RemoteRunOptions(
            host="fake-gpu",
            remote_dir="/tmp/remote-bundle",
            local_dir=tmp_path / "local-run",
            provider_name="mock",
            kind="video",
        ),
        runner=runner,
        dry_run=True,
    )

    assert summary["dry_run"] is True
    assert runner.commands == []
    assert not (tmp_path / "local-run" / "bundle").exists()
    assert not (demo_project_files / "manifest.json").exists()


def test_run_remote_worker_failed_upload_does_not_import(demo_project_files, tmp_path):
    project = load_project(demo_project_files)
    runner = FailingUploadRunner()

    with pytest.raises(ProviderError):
        run_remote_worker(
            project,
            RemoteRunOptions(
                host="fake-gpu",
                remote_dir="/tmp/remote-bundle",
                local_dir=tmp_path / "local-run",
                provider_name="mock",
                kind="video",
            ),
            runner=runner,
        )

    assert len(runner.commands) == 1
    assert not (demo_project_files / "manifest.json").exists()
```

- [ ] **Step 2: Run orchestration tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_remote_transport.py::test_run_remote_worker_exports_runs_downloads_and_imports tests/test_remote_transport.py::test_run_remote_worker_dry_run_does_not_export_or_import tests/test_remote_transport.py::test_run_remote_worker_failed_upload_does_not_import -v
```

Expected: FAIL because `run_remote_worker` is not defined.

- [ ] **Step 3: Add remote orchestration**

First, add this import to the existing import block in `src/auto_video/remote_transport.py`:

```python
from .worker_bundle import export_worker_bundle, import_worker_results
```

Then append this orchestration code to the end of `src/auto_video/remote_transport.py`:

```python


def _base_summary(project: Project, plan: RemoteRunPlan, *, dry_run: bool) -> dict[str, Any]:
    return {
        "dry_run": dry_run,
        "project": project.config.name,
        "host": plan.host,
        "remote_dir": plan.remote_dir,
        "local_bundle": plan.local_bundle.as_posix(),
        "commands": plan.commands_dict(),
    }


def run_remote_worker(
    project: Project,
    options: RemoteRunOptions,
    *,
    runner: CommandRunner | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    plan = build_remote_run_plan(project, options)
    summary = _base_summary(project, plan, dry_run=dry_run)
    if dry_run:
        summary["import_action"] = {
            "project": project.config.root.as_posix(),
            "bundle": plan.local_bundle.as_posix(),
        }
        return summary

    export_worker_bundle(
        project,
        plan.local_bundle,
        kind=options.kind,
        provider_name=options.provider_name,
        only=options.only,
        force=True,
    )
    command_runner = runner or SubprocessCommandRunner()
    command_runner.run(plan.upload)
    command_runner.run(plan.run)
    command_runner.run(plan.download)
    import_summary = import_worker_results(project.config.root, plan.local_bundle)
    return {
        **summary,
        "imported": import_summary["imported"],
        "failed": import_summary["failed"],
    }
```

- [ ] **Step 4: Run remote transport tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_remote_transport.py -v
```

Expected: PASS.

- [ ] **Step 5: Run worker tests for regression coverage**

Run:

```bash
.venv/bin/python -m pytest tests/test_worker_bundle.py tests/test_worker_runner.py tests/test_worker_import.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/auto_video/remote_transport.py tests/test_remote_transport.py
git commit -m "feat: run remote worker transport"
```

## Task 3: Remote CLI Command

**Files:**
- Modify: `src/auto_video/cli.py`
- Create: `tests/test_remote_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_remote_cli.py`:

```python
import json
import shutil
from pathlib import Path

from auto_video import remote_transport
from auto_video.cli import main
from auto_video.remote_transport import CommandResult
from auto_video.worker_runner import run_worker_bundle


class CliFakeRemoteRunner:
    def __init__(self, remote_bundle: Path):
        self.remote_bundle = remote_bundle
        self.commands: list[tuple[str, ...]] = []

    def run(self, command):
        command = tuple(command)
        self.commands.append(command)
        if len(self.commands) == 1:
            shutil.copytree(Path(command[-2]), self.remote_bundle, dirs_exist_ok=True)
        elif len(self.commands) == 2:
            run_worker_bundle(self.remote_bundle)
        elif len(self.commands) == 3:
            shutil.copytree(self.remote_bundle, Path(command[-1]), dirs_exist_ok=True)
        return CommandResult(command=command)


def test_remote_cli_dry_run_prints_commands_without_manifest(tmp_path: Path, capsys):
    project = tmp_path / "demo"
    local_dir = tmp_path / "remote-work"
    assert main(["init", str(project)]) == 0

    assert (
        main(
            [
                "remote",
                "run",
                str(project),
                "--provider",
                "mock",
                "--kind",
                "video",
                "--host",
                "gpu-box",
                "--remote-dir",
                "/data/auto-video/jobs/demo",
                "--local-dir",
                str(local_dir),
                "--ssh-option",
                "StrictHostKeyChecking=no",
                "--dry-run",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["dry_run"] is True
    assert payload["host"] == "gpu-box"
    assert payload["remote_dir"] == "/data/auto-video/jobs/demo"
    assert payload["commands"]["run"] == [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "gpu-box",
        "auto-video",
        "worker",
        "run",
        "/data/auto-video/jobs/demo",
    ]
    assert not (project / "manifest.json").exists()
    assert not (local_dir / "bundle").exists()


def test_remote_cli_fake_execution_imports_manifest(tmp_path: Path, monkeypatch, capsys):
    project = tmp_path / "demo"
    local_dir = tmp_path / "remote-work"
    remote_bundle = tmp_path / "fake-remote-bundle"
    fake_runner = CliFakeRemoteRunner(remote_bundle)
    monkeypatch.setattr(remote_transport, "SubprocessCommandRunner", lambda: fake_runner)
    assert main(["init", str(project)]) == 0

    assert (
        main(
            [
                "remote",
                "run",
                str(project),
                "--provider",
                "mock",
                "--kind",
                "video",
                "--host",
                "fake-gpu",
                "--remote-dir",
                "/tmp/remote-bundle",
                "--local-dir",
                str(local_dir),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert [command[0] for command in fake_runner.commands] == ["rsync", "ssh", "rsync"]
    assert payload["dry_run"] is False
    assert payload["imported"] == ["demo_ad:S01:video:mock"]
    assert payload["failed"] == []
    assert (project / "manifest.json").exists()
    assert (project / "generated" / "clips" / "S01.mp4").exists()
```

- [ ] **Step 2: Run CLI tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_remote_cli.py -v
```

Expected: FAIL because `remote` is not a recognized command.

- [ ] **Step 3: Add CLI imports**

Modify `src/auto_video/cli.py` imports:

```python
from .remote_transport import RemoteRunOptions, run_remote_worker
```

- [ ] **Step 4: Add remote parser**

In `build_parser()`, before `providers = sub.add_parser("providers")`, add:

```python
    remote = sub.add_parser("remote")
    remote_sub = remote.add_subparsers(dest="remote_command")

    remote_run = remote_sub.add_parser("run")
    remote_run.add_argument("project")
    remote_run.add_argument("--host", required=True)
    remote_run.add_argument("--remote-dir", required=True)
    remote_run.add_argument("--provider")
    remote_run.add_argument("--kind", choices=["image", "video", "audio"], default="video")
    remote_run.add_argument("--only")
    remote_run.add_argument("--local-dir")
    remote_run.add_argument("--remote-auto-video", default="auto-video")
    remote_run.add_argument("--ssh-option", action="append", default=[])
    remote_run.add_argument("--rsync-option", action="append", default=[])
    remote_run.add_argument("--dry-run", action="store_true")
```

- [ ] **Step 5: Add remote command handling**

In `main()`, before the existing `providers` block, add:

```python
        if args.command == "remote" and args.remote_command == "run":
            project = load_project(args.project)
            result = run_remote_worker(
                project,
                RemoteRunOptions(
                    host=args.host,
                    remote_dir=args.remote_dir,
                    provider_name=args.provider,
                    kind=args.kind,
                    only=_csv(args.only),
                    local_dir=Path(args.local_dir) if args.local_dir else None,
                    remote_auto_video=args.remote_auto_video,
                    ssh_options=tuple(args.ssh_option),
                    rsync_options=tuple(args.rsync_option),
                ),
                dry_run=args.dry_run,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
```

- [ ] **Step 6: Run remote CLI tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_remote_cli.py -v
```

Expected: PASS.

- [ ] **Step 7: Run existing CLI tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli.py tests/test_cli_jobs.py tests/test_worker_cli.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/auto_video/cli.py tests/test_remote_cli.py
git commit -m "feat: add remote worker CLI"
```

## Task 4: README And Checked-In Dry Run

**Files:**
- Modify: `README.md`
- Modify: `tests/test_remote_cli.py`

- [ ] **Step 1: Add checked-in example dry-run test**

Append to `tests/test_remote_cli.py`:

```python
def test_checked_in_example_remote_dry_run(tmp_path: Path, capsys):
    local_dir = tmp_path / "example-remote-work"

    assert (
        main(
            [
                "remote",
                "run",
                "examples/demo_project",
                "--provider",
                "mock",
                "--kind",
                "video",
                "--host",
                "gpu-box",
                "--remote-dir",
                "/data/auto-video/jobs/demo",
                "--local-dir",
                str(local_dir),
                "--dry-run",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["dry_run"] is True
    assert payload["commands"]["upload"][0] == "rsync"
    assert payload["commands"]["run"][0] == "ssh"
    assert not (Path("examples/demo_project") / "manifest.json").exists()
```

- [ ] **Step 2: Run checked-in example dry-run test**

Run:

```bash
.venv/bin/python -m pytest tests/test_remote_cli.py::test_checked_in_example_remote_dry_run -v
```

Expected: PASS.

- [ ] **Step 3: Update README workflow block**

Modify the MVP workflow block in `README.md` to include:

```bash
.venv/bin/python -m auto_video remote run demo_project --provider mock --kind video --host gpu-box --remote-dir /data/auto-video/jobs/demo --local-dir /tmp/av-remote-demo --dry-run
```

- [ ] **Step 4: Add README section**

Add this section after "Cloud Worker Contract":

```markdown
## SSH Remote Worker Transport

Phase 4 adds a thin SSH/rsync transport around worker bundles:

    .venv/bin/python -m auto_video remote run demo_project --provider mock --kind video --host gpu-box --remote-dir /data/auto-video/jobs/demo --local-dir /tmp/av-remote-demo --dry-run

Without `--dry-run`, the command exports a local worker bundle, uploads it with `rsync`, runs `auto-video worker run` over `ssh`, downloads the updated bundle, and imports the result into the local project manifest.

The remote host must already have SSH access, `rsync`, a working `auto-video` command, and any provider runtime or GPU dependencies required by the selected provider. Phase 4 does not create cloud machines or install GPU runtimes.
```

- [ ] **Step 5: Run remote CLI tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_remote_cli.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add README.md tests/test_remote_cli.py
git commit -m "docs: document ssh remote worker workflow"
```

## Task 5: Full Verification And Remote Sync

**Files:**
- No source changes expected unless verification exposes an issue.

- [ ] **Step 1: Run full test suite**

Run:

```bash
.venv/bin/python -m pytest -v
```

Expected: all tests PASS.

- [ ] **Step 2: Run CLI dry-run smoke for remote workflow**

Run:

```bash
set -euo pipefail
TMPDIR="$(mktemp -d)"
.venv/bin/python -m auto_video init "$TMPDIR/demo"
.venv/bin/python -m auto_video remote run "$TMPDIR/demo" --provider mock --kind video --host gpu-box --remote-dir /data/auto-video/jobs/demo --local-dir "$TMPDIR/remote-work" --dry-run >/tmp/auto_video_remote_dry_run.json
test ! -e "$TMPDIR/demo/manifest.json"
test ! -e "$TMPDIR/remote-work/bundle"
.venv/bin/python -m auto_video jobs status "$TMPDIR/demo" >/tmp/auto_video_remote_empty_jobs.json
```

Expected:

- `remote run --dry-run` exits 0.
- The dry run output contains `rsync` and `ssh` commands.
- The project has no `manifest.json`.
- The local bundle is not created during dry run.
- `jobs status` exits 0 and reports no jobs.

- [ ] **Step 3: Run unit-level fake remote workflow**

Run:

```bash
.venv/bin/python -m pytest tests/test_remote_transport.py::test_run_remote_worker_exports_runs_downloads_and_imports tests/test_remote_cli.py::test_remote_cli_fake_execution_imports_manifest -v
```

Expected: PASS.

- [ ] **Step 4: Check git status**

Run:

```bash
git status --short --branch
```

Expected: clean working tree on `main`.

- [ ] **Step 5: Push to GitHub**

Run:

```bash
git push origin main
```

Expected: `main` is pushed to `origin/main`.

## Self-Review

Spec coverage:

- `auto-video remote run` is covered by Task 3.
- Bundle export, upload, remote run, download, and import orchestration are covered by Task 2.
- SSH and rsync command planning is covered by Task 1.
- `--dry-run` behavior is covered by Task 2, Task 3, and Task 5.
- Offline fake remote execution is covered by Task 2 and Task 3.
- Unsafe host, remote path, and local path handling is covered by Task 1.
- README documentation and checked-in example dry run are covered by Task 4.
- Full verification and GitHub sync are covered by Task 5.

Intentional gaps:

- Real cloud VM provisioning, remote setup, Docker, object storage, async queues, provider-specific cloud profiles, and real GPU providers remain future work.
