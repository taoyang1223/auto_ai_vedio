from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import ConfigError
from .models import Project
from .remote_transport import RemoteRunOptions


REMOTE_PROFILE_KEYS = {
    "host",
    "remote_dir",
    "local_dir",
    "remote_auto_video",
    "ssh_options",
    "rsync_options",
    "remote_env",
}


def list_remote_profiles(project: Project) -> list[str]:
    return sorted(project.config.remote_profiles)


def build_remote_run_options_from_profile(
    project: Project,
    *,
    profile_name: str | None,
    host: str | None,
    remote_dir: str | None,
    provider_name: str | None,
    kind: str,
    only: set[str] | None,
    local_dir: Path | None,
    remote_auto_video: str | None,
    ssh_options: tuple[str, ...],
    rsync_options: tuple[str, ...],
    remote_env: tuple[str, ...],
) -> RemoteRunOptions:
    profile = _profile(project, profile_name)
    return RemoteRunOptions(
        host=host or _optional_str(profile, "host") or _missing_profile_value("host", profile_name),
        remote_dir=(
            remote_dir
            or _optional_str(profile, "remote_dir")
            or _missing_profile_value("remote-dir", profile_name)
        ),
        provider_name=provider_name,
        kind=kind,
        only=only,
        local_dir=local_dir or _optional_path(profile, "local_dir"),
        remote_auto_video=remote_auto_video or _optional_str(profile, "remote_auto_video") or "auto-video",
        ssh_options=(*_string_list(profile, "ssh_options"), *ssh_options),
        rsync_options=(*_string_list(profile, "rsync_options"), *rsync_options),
        remote_env=_merge_env(_env_assignments(profile, "remote_env"), remote_env),
    )


def _profile(project: Project, profile_name: str | None) -> dict[str, Any]:
    if profile_name is None:
        return {}
    profiles = project.config.remote_profiles
    if profile_name not in profiles:
        choices = ", ".join(sorted(profiles)) or "no profiles configured"
        raise ConfigError(
            f"remote profile {profile_name!r} is not configured",
            fix=f"Choose one of: {choices}, or omit --profile and pass --host/--remote-dir.",
        )
    raw = profiles[profile_name]
    unknown = sorted(set(raw) - REMOTE_PROFILE_KEYS)
    if unknown:
        raise ConfigError(
            f"remote profile {profile_name!r} has unsupported keys: {', '.join(unknown)}",
            fix=f"Use supported keys: {', '.join(sorted(REMOTE_PROFILE_KEYS))}.",
        )
    return raw


def _missing_profile_value(name: str, profile_name: str | None) -> str:
    if profile_name:
        raise ConfigError(
            f"remote profile {profile_name!r} missing {name}",
            fix=f"Add {name} to the profile or pass --{name} on the command line.",
        )
    raise ConfigError(f"--{name} is required", fix=f"Pass --{name} or use --profile with {name} configured.")


def _optional_str(profile: dict[str, Any], key: str) -> str | None:
    value = profile.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"remote profile {key} must be a string", fix=f"Use a string value for {key}.")
    return value


def _optional_path(profile: dict[str, Any], key: str) -> Path | None:
    value = _optional_str(profile, key)
    return Path(value) if value else None


def _string_list(profile: dict[str, Any], key: str) -> tuple[str, ...]:
    value = profile.get(key)
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"remote profile {key} must be a list of strings", fix=f"Use YAML list syntax for {key}.")
    return tuple(value)


def _env_assignments(profile: dict[str, Any], key: str) -> tuple[str, ...]:
    value = profile.get(key)
    if value is None:
        return ()
    if isinstance(value, dict):
        return tuple(f"{name}={env_value}" for name, env_value in value.items())
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise ConfigError(
        f"remote profile {key} must be a mapping or list of NAME=value strings",
        fix="Use YAML mapping syntax for environment variables.",
    )


def _merge_env(profile_env: tuple[str, ...], cli_env: tuple[str, ...]) -> tuple[str, ...]:
    merged: dict[str, str] = {}
    order: list[str] = []
    for item in (*profile_env, *cli_env):
        name = item.split("=", 1)[0] if "=" in item else item
        if name not in merged:
            order.append(name)
        merged[name] = item
    return tuple(merged[name] for name in order)
