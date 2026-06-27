from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Protocol

from auto_video.jobs import GenerationJob, ProviderResult
from auto_video.models import ProviderConfig
from auto_video.project import resolve_project_path
from auto_video.worker_bundle import safe_bundle_filename

SNIPPET_LIMIT = 1000


class TTSCommandRunner(Protocol):
    def run(self, command: tuple[str, ...], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        ...


class SubprocessTTSRunner:
    def run(self, command: tuple[str, ...], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=os.environ.copy(),
        )


class LocalTTSProvider:
    def __init__(self, name: str, config: ProviderConfig | None = None, runner: TTSCommandRunner | None = None):
        self.name = name
        self.config = config or ProviderConfig(mode="local_tts", timeout_seconds=180)
        self.runner = runner or SubprocessTTSRunner()

    def execute_job(self, job: GenerationJob, project_root: Path) -> ProviderResult:
        if job.kind != "audio":
            return ProviderResult(
                job_id=job.id,
                shot_id=job.shot_id,
                kind=job.kind,
                provider=self.name,
                status="failed",
                error="local_tts provider only supports audio jobs",
                metadata={"local_tts": {"engine": self._engine()}},
            )

        project_root = project_root.resolve()
        output_path = resolve_project_path(project_root, job.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        text = _voice_text(job, self.config)
        duration = float(job.duration or 0)
        if not text:
            return self._write_silence(job, project_root, output_path, duration, reason="empty_text")

        engine = self._engine()
        if engine == "silence":
            return self._write_silence(job, project_root, output_path, duration, reason="engine_silence")
        if engine == "edge_tts":
            return self._run_edge_tts(job, project_root, output_path, text, duration)
        if engine in {"espeak", "espeak_ng"}:
            return self._run_espeak(job, project_root, output_path, text, duration, engine=engine)
        return ProviderResult(
            job_id=job.id,
            shot_id=job.shot_id,
            kind=job.kind,
            provider=self.name,
            status="failed",
            error=f"unsupported local_tts engine {engine!r}",
            metadata={"local_tts": {"engine": engine}},
        )

    def _engine(self) -> str:
        return str(self.config.options.get("engine") or "edge_tts")

    def _run_edge_tts(
        self,
        job: GenerationJob,
        project_root: Path,
        output_path: Path,
        text: str,
        duration: float,
    ) -> ProviderResult:
        command_name = str(self.config.options.get("command") or "edge-tts")
        if not shutil.which(command_name):
            return ProviderResult(
                job_id=job.id,
                shot_id=job.shot_id,
                kind=job.kind,
                provider=self.name,
                status="failed",
                error=f"missing command {command_name!r}",
                metadata={
                    "local_tts": {
                        "engine": "edge_tts",
                        "fix": "Install edge-tts or change providers.local_tts.engine to espeak/silence.",
                    }
                },
            )
        temp_media = _temp_media_path(project_root, job, ".mp3")
        temp_media.parent.mkdir(parents=True, exist_ok=True)
        voice = _voice(job, self.config, default="zh-CN-XiaoxiaoNeural")
        command = (
            command_name,
            "--voice",
            voice,
            "--text",
            text,
            "--write-media",
            temp_media.as_posix(),
        )
        for option_name, flag in (("rate", "--rate"), ("volume", "--volume"), ("pitch", "--pitch")):
            value = self.config.options.get(option_name)
            if value not in (None, ""):
                command = (*command, flag, str(value))
        completed = self._run_command(command, project_root)
        metadata = {
            "local_tts": {
                "engine": "edge_tts",
                "voice": voice,
                "speaker": str(job.metadata.get("speaker") or ""),
                "text_source": _text_source(self.config),
                "text_chars": len(text),
                "synthesis": _completed_payload(command, completed),
            }
        }
        if completed.returncode != 0:
            return _failed(job, self.name, f"edge-tts failed with exit code {completed.returncode}", metadata)
        return self._normalize(job, project_root, temp_media, output_path, duration, metadata)

    def _run_espeak(
        self,
        job: GenerationJob,
        project_root: Path,
        output_path: Path,
        text: str,
        duration: float,
        *,
        engine: str,
    ) -> ProviderResult:
        command_name = str(self.config.options.get("command") or ("espeak-ng" if engine == "espeak_ng" else "espeak"))
        if not shutil.which(command_name):
            return ProviderResult(
                job_id=job.id,
                shot_id=job.shot_id,
                kind=job.kind,
                provider=self.name,
                status="failed",
                error=f"missing command {command_name!r}",
                metadata={"local_tts": {"engine": engine}},
            )
        temp_media = _temp_media_path(project_root, job, ".wav")
        temp_media.parent.mkdir(parents=True, exist_ok=True)
        voice = _voice(job, self.config, default="zh")
        command = (
            command_name,
            "-v",
            voice,
            "-w",
            temp_media.as_posix(),
            text,
        )
        completed = self._run_command(command, project_root)
        metadata = {
            "local_tts": {
                "engine": engine,
                "voice": voice,
                "speaker": str(job.metadata.get("speaker") or ""),
                "text_source": _text_source(self.config),
                "text_chars": len(text),
                "synthesis": _completed_payload(command, completed),
            }
        }
        if completed.returncode != 0:
            return _failed(job, self.name, f"{command_name} failed with exit code {completed.returncode}", metadata)
        return self._normalize(job, project_root, temp_media, output_path, duration, metadata)

    def _write_silence(
        self,
        job: GenerationJob,
        project_root: Path,
        output_path: Path,
        duration: float,
        *,
        reason: str,
    ) -> ProviderResult:
        command = _silence_command(self.config, output_path, duration)
        completed = self._run_command(command, project_root)
        metadata = {
            "local_tts": {
                "engine": "silence",
                "reason": reason,
                "text_source": _text_source(self.config),
                "synthesis": _completed_payload(command, completed),
            }
        }
        if completed.returncode != 0:
            return _failed(job, self.name, f"ffmpeg silence generation failed with exit code {completed.returncode}", metadata)
        return _succeeded(job, self.name, output_path, duration, metadata)

    def _normalize(
        self,
        job: GenerationJob,
        project_root: Path,
        input_path: Path,
        output_path: Path,
        duration: float,
        metadata: dict,
    ) -> ProviderResult:
        command = _normalize_command(self.config, input_path, output_path, duration)
        completed = self._run_command(command, project_root)
        metadata["local_tts"]["normalize"] = _completed_payload(command, completed)
        if completed.returncode != 0:
            return _failed(job, self.name, f"ffmpeg audio normalization failed with exit code {completed.returncode}", metadata)
        if not output_path.exists():
            return _failed(job, self.name, f"TTS output was not created: {output_path.as_posix()}", metadata)
        return _succeeded(job, self.name, output_path, duration, metadata)

    def _run_command(self, command: tuple[str, ...], project_root: Path) -> subprocess.CompletedProcess[str]:
        try:
            return self.runner.run(command, cwd=project_root, timeout=int(self.config.timeout_seconds))
        except subprocess.TimeoutExpired as exc:
            return subprocess.CompletedProcess(command, 124, stdout=exc.stdout or "", stderr=exc.stderr or "timeout")
        except OSError as exc:
            return subprocess.CompletedProcess(command, 127, stdout="", stderr=str(exc))


def _voice_text(job: GenerationJob, config: ProviderConfig) -> str:
    controls = job.controls
    source = _text_source(config)
    if source == "prompt":
        return job.prompt.strip()
    if source == "audio_intent":
        return (controls.audio_intent if controls else "").strip()
    if source == "subtitle_or_prompt":
        return ((controls.subtitle if controls else "") or job.prompt).strip()
    return (controls.subtitle if controls else "").strip()


def _voice(job: GenerationJob, config: ProviderConfig, *, default: str) -> str:
    controls_voice = job.controls.voice if job.controls else ""
    return str(job.metadata.get("voice") or controls_voice or config.options.get("voice") or default)


def _text_source(config: ProviderConfig) -> str:
    return str(config.options.get("text_source") or "subtitle")


def _sample_rate(config: ProviderConfig) -> int:
    return max(8000, int(config.options.get("sample_rate") or 48000))


def _channels(config: ProviderConfig) -> int:
    return 1 if int(config.options.get("channels") or 2) == 1 else 2


def _ffmpeg(config: ProviderConfig) -> str:
    return str(config.options.get("ffmpeg") or "ffmpeg")


def _normalize_command(config: ProviderConfig, input_path: Path, output_path: Path, duration: float) -> tuple[str, ...]:
    command = (
        _ffmpeg(config),
        "-y",
        "-i",
        input_path.as_posix(),
    )
    if duration > 0:
        command = (*command, "-filter:a", f"apad=whole_dur={duration:.3f},atrim=0:{duration:.3f}")
    return (
        *command,
        "-ar",
        str(_sample_rate(config)),
        "-ac",
        str(_channels(config)),
        output_path.as_posix(),
    )


def _silence_command(config: ProviderConfig, output_path: Path, duration: float) -> tuple[str, ...]:
    channel_layout = "mono" if _channels(config) == 1 else "stereo"
    seconds = max(0.2, duration or float(config.options.get("default_duration") or 1.0))
    return (
        _ffmpeg(config),
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={_sample_rate(config)}:cl={channel_layout}",
        "-t",
        f"{seconds:.3f}",
        "-ar",
        str(_sample_rate(config)),
        "-ac",
        str(_channels(config)),
        output_path.as_posix(),
    )


def _temp_media_path(project_root: Path, job: GenerationJob, suffix: str) -> Path:
    stem = safe_bundle_filename(job.id).removesuffix(".json")
    return project_root / ".auto-video" / "tts" / f"{stem}{suffix}"


def _completed_payload(command: tuple[str, ...], completed: subprocess.CompletedProcess[str]) -> dict:
    return {
        "command": list(command),
        "returncode": completed.returncode,
        "stdout": _snippet(completed.stdout),
        "stderr": _snippet(completed.stderr),
    }


def _snippet(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    value = value.strip()
    if len(value) <= SNIPPET_LIMIT:
        return value
    return value[: SNIPPET_LIMIT - 3] + "..."


def _failed(job: GenerationJob, provider: str, error: str, metadata: dict) -> ProviderResult:
    return ProviderResult(
        job_id=job.id,
        shot_id=job.shot_id,
        kind=job.kind,
        provider=provider,
        status="failed",
        error=error,
        metadata=metadata,
    )


def _succeeded(job: GenerationJob, provider: str, output_path: Path, duration: float, metadata: dict) -> ProviderResult:
    return ProviderResult(
        job_id=job.id,
        shot_id=job.shot_id,
        kind=job.kind,
        provider=provider,
        status="succeeded",
        path=output_path,
        duration=duration or job.duration,
        metadata=metadata,
    )
