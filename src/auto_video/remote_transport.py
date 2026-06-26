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
