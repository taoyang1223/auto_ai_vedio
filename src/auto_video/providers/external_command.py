from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from auto_video.errors import ConfigError
from auto_video.jobs import GenerationJob, ProviderResult
from auto_video.models import ProviderConfig
from auto_video.project import resolve_project_path
from auto_video.worker_bundle import safe_bundle_filename

UNSAFE_COMMAND_CHARS = set("\n\r\0")
SNIPPET_LIMIT = 1000


class ExternalCommandProvider:
    def __init__(self, name: str, config: ProviderConfig):
        self.name = name
        self.config = config
        self.command = _command_from_config(config)

    def execute_job(self, job: GenerationJob, project_root: Path) -> ProviderResult:
        project_root = project_root.resolve()
        output_path = resolve_project_path(project_root, job.output_path)
        payload_path = _payload_path(project_root, job)
        payload = _job_payload(job, project_root, output_path)
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        command = (
            *self.command,
            "--job",
            payload_path.as_posix(),
            "--project-root",
            project_root.as_posix(),
            "--output",
            output_path.as_posix(),
        )
        try:
            completed = subprocess.run(
                list(command),
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return ProviderResult(
                job_id=job.id,
                shot_id=job.shot_id,
                kind=job.kind,
                provider=self.name,
                status="retryable_failed",
                error=f"external command timed out after {self.config.timeout_seconds} seconds",
                retryable=True,
                metadata={
                    "external_command": {
                        "command": list(command),
                        "stdout": _snippet(exc.stdout or ""),
                        "stderr": _snippet(exc.stderr or ""),
                    }
                },
            )
        except OSError as exc:
            return ProviderResult(
                job_id=job.id,
                shot_id=job.shot_id,
                kind=job.kind,
                provider=self.name,
                status="failed",
                error=f"external command could not start: {exc}",
                metadata={"external_command": {"command": list(command)}},
            )

        metadata = {
            "external_command": {
                "command": list(command),
                "returncode": completed.returncode,
                "stdout": _snippet(completed.stdout),
                "stderr": _snippet(completed.stderr),
            }
        }
        if completed.returncode != 0:
            return ProviderResult(
                job_id=job.id,
                shot_id=job.shot_id,
                kind=job.kind,
                provider=self.name,
                status="failed",
                error=f"external command failed with exit code {completed.returncode}",
                metadata=metadata,
            )
        if not output_path.exists():
            return ProviderResult(
                job_id=job.id,
                shot_id=job.shot_id,
                kind=job.kind,
                provider=self.name,
                status="failed",
                error=f"external command did not create output {output_path.as_posix()}",
                metadata=metadata,
            )
        return ProviderResult(
            job_id=job.id,
            shot_id=job.shot_id,
            kind=job.kind,
            provider=self.name,
            status="succeeded",
            path=output_path,
            duration=job.duration,
            metadata=metadata,
        )


def _command_from_config(config: ProviderConfig) -> tuple[str, ...]:
    raw = config.options.get("command")
    if not isinstance(raw, list) or not raw:
        raise ConfigError(
            "external_command provider requires a non-empty command list",
            fix="Set providers.<name>.command to a YAML list of command tokens.",
        )
    command: list[str] = []
    for index, token in enumerate(raw):
        if not isinstance(token, str) or not token:
            raise ConfigError(
                f"external_command command[{index}] must be a non-empty string",
                fix="Use strings for every command token.",
            )
        if any(char in UNSAFE_COMMAND_CHARS for char in token):
            raise ConfigError(
                f"external_command command[{index}] contains unsafe control characters",
                fix="Remove newline, carriage return, or NUL characters from command tokens.",
            )
        command.append(token)
    return tuple(command)


def _payload_path(project_root: Path, job: GenerationJob) -> Path:
    return project_root / ".auto-video" / "provider-jobs" / safe_bundle_filename(job.id)


def _job_payload(job: GenerationJob, project_root: Path, output_path: Path) -> dict[str, Any]:
    return {
        "job": job.to_dict(),
        "project_root": project_root.as_posix(),
        "output_path": output_path.as_posix(),
        "references": [_reference_payload(ref, project_root) for ref in job.refs],
    }


def _reference_payload(ref, project_root: Path) -> dict[str, Any]:
    absolute_path = resolve_project_path(project_root, ref.path)
    return {
        **ref.to_dict(),
        "absolute_path": absolute_path.as_posix(),
        "exists": absolute_path.exists(),
    }


def _snippet(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    stripped = value.strip()
    if len(stripped) <= SNIPPET_LIMIT:
        return stripped
    return stripped[: SNIPPET_LIMIT - 3] + "..."
