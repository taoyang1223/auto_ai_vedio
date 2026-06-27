from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .errors import ProbeError


class MediaProbeRunner(Protocol):
    def probe(self, path: Path) -> dict[str, Any]:
        """Return ffprobe JSON for a media file."""

    def blackdetect(self, path: Path) -> str:
        """Return ffmpeg blackdetect stderr for a media file."""


@dataclass(frozen=True)
class SubprocessMediaProbeRunner:
    ffprobe: str = "ffprobe"
    ffmpeg: str = "ffmpeg"

    def probe(self, path: Path) -> dict[str, Any]:
        command = (
            self.ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            path.as_posix(),
        )
        try:
            completed = subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise ProbeError("missing command 'ffprobe'", fix="Install ffprobe to inspect generated videos.") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise ProbeError("ffprobe failed while inspecting media", fix=stderr or "Regenerate the clip.") from exc
        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise ProbeError("ffprobe returned invalid JSON", fix=str(exc)) from exc
        if not isinstance(payload, dict):
            raise ProbeError("ffprobe returned non-object JSON", fix="Check the media file and ffprobe version.")
        return payload

    def blackdetect(self, path: Path) -> str:
        command = (
            self.ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            path.as_posix(),
            "-vf",
            "blackdetect=d=0.5:pix_th=0.10",
            "-an",
            "-f",
            "null",
            "-",
        )
        try:
            completed = subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise ProbeError("missing command 'ffmpeg'", fix="Install ffmpeg to run black-frame checks.") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise ProbeError("ffmpeg blackdetect failed", fix=stderr or "Regenerate the clip.") from exc
        return completed.stderr or ""


def inspect_media(payload: dict[str, Any]) -> dict[str, Any]:
    stream = _first_video_stream(payload)
    if stream is None:
        raise ProbeError("media has no video stream", fix="Regenerate the shot or check provider output.")
    fmt = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    duration = _float_or_none(stream.get("duration")) or _float_or_none(fmt.get("duration"))
    fps = _rate(stream.get("avg_frame_rate")) or _rate(stream.get("r_frame_rate"))
    return {
        "width": _int_or_none(stream.get("width")),
        "height": _int_or_none(stream.get("height")),
        "duration": duration,
        "fps": fps,
        "codec": stream.get("codec_name"),
        "pix_fmt": stream.get("pix_fmt"),
        "bit_rate": _int_or_none(stream.get("bit_rate")) or _int_or_none(fmt.get("bit_rate")),
    }


def build_media_checks(
    media: dict[str, Any],
    *,
    shot_id: str,
    expected_width: int,
    expected_height: int,
    expected_fps: int,
    target_duration: float,
    min_duration_ratio: float,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    width = media.get("width")
    height = media.get("height")
    if width == expected_width and height == expected_height:
        checks.append(_ok("media_resolution", shot_id, f"resolution is {width}x{height}"))
    else:
        checks.append(
            _failed(
                "media_resolution",
                shot_id,
                f"resolution is {width}x{height}; expected {expected_width}x{expected_height}",
                "Regenerate with project width/height or update project.yaml to match the workflow.",
            )
        )

    duration = media.get("duration")
    min_duration = target_duration * min_duration_ratio
    if duration is None:
        checks.append(
            _warning(
                "media_duration",
                shot_id,
                "duration is unavailable",
                "Check ffprobe output or regenerate the clip.",
            )
        )
    elif duration < min_duration:
        checks.append(
            _failed(
                "media_duration",
                shot_id,
                f"duration is {duration:.3f}s; expected at least {min_duration:.3f}s",
                "Regenerate the shot or lower the shot duration in shots.json.",
            )
        )
    else:
        checks.append(_ok("media_duration", shot_id, f"duration is {duration:.3f}s"))

    fps = media.get("fps")
    if fps is None:
        checks.append(_warning("media_fps", shot_id, "fps is unavailable", "Check ffprobe output."))
    elif abs(float(fps) - float(expected_fps)) > 0.5:
        checks.append(
            _failed(
                "media_fps",
                shot_id,
                f"fps is {fps:.3f}; expected {expected_fps}",
                "Regenerate with the project fps or update project.yaml to match the workflow.",
            )
        )
    else:
        checks.append(_ok("media_fps", shot_id, f"fps is {fps:.3f}"))
    return checks


def build_blackdetect_check(
    stderr: str,
    *,
    shot_id: str,
    duration: float | None,
    max_black_ratio: float,
) -> dict[str, Any]:
    segments = _black_segments(stderr)
    black_duration = sum(segment["duration"] for segment in segments)
    ratio = round(black_duration / duration, 4) if duration and duration > 0 else None
    payload = {
        "name": "blackdetect",
        "shot_id": shot_id,
        "black_duration": round(black_duration, 4),
        "black_ratio": ratio,
        "segments": segments,
    }
    if ratio is not None and ratio >= max_black_ratio:
        return {
            **payload,
            "status": "failed",
            "message": f"black frames cover {ratio:.1%} of the clip",
            "fix": "Regenerate the shot or replace the first-frame reference.",
        }
    if segments:
        return {
            **payload,
            "status": "warning",
            "message": f"detected {len(segments)} black segment(s)",
            "fix": "Review the clip manually if the dark scene was not intentional.",
        }
    return {**payload, "status": "ok", "message": "no black segments detected"}


def status_from_checks(checks: list[dict[str, Any]]) -> str:
    statuses = {check.get("status") for check in checks}
    if "failed" in statuses:
        return "failed"
    if "warning" in statuses:
        return "warning"
    if "skipped" in statuses:
        return "skipped"
    return "ok"


def summarize_checks(shots: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"shots": len(shots), "ok": 0, "warning": 0, "failed": 0, "skipped": 0}
    for shot in shots:
        status = str(shot.get("quality_status", "skipped"))
        if status not in summary:
            status = "skipped"
        summary[status] += 1
    return summary


def _first_video_stream(payload: dict[str, Any]) -> dict[str, Any] | None:
    streams = payload.get("streams")
    if not isinstance(streams, list):
        return None
    for stream in streams:
        if isinstance(stream, dict) and stream.get("codec_type") == "video":
            return stream
    return None


def _rate(value: Any) -> float | None:
    if not value:
        return None
    text = str(value)
    if "/" not in text:
        return _float_or_none(text)
    numerator, denominator = text.split("/", 1)
    top = _float_or_none(numerator)
    bottom = _float_or_none(denominator)
    if top is None or bottom in (None, 0):
        return None
    return top / bottom


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _black_segments(stderr: str) -> list[dict[str, float]]:
    segments: list[dict[str, float]] = []
    for line in stderr.splitlines():
        if "black_start:" not in line or "black_end:" not in line or "black_duration:" not in line:
            continue
        values: dict[str, float] = {}
        for token in line.split():
            if ":" not in token:
                continue
            key, value = token.split(":", 1)
            if key not in {"black_start", "black_end", "black_duration"}:
                continue
            parsed = _float_or_none(value)
            if parsed is not None:
                values[key.removeprefix("black_")] = parsed
        if {"start", "end", "duration"} <= set(values):
            segments.append(values)
    return segments


def _ok(name: str, shot_id: str, message: str) -> dict[str, Any]:
    return {"name": name, "shot_id": shot_id, "status": "ok", "message": message}


def _warning(name: str, shot_id: str, message: str, fix: str) -> dict[str, Any]:
    return {"name": name, "shot_id": shot_id, "status": "warning", "message": message, "fix": fix}


def _failed(name: str, shot_id: str, message: str, fix: str) -> dict[str, Any]:
    return {"name": name, "shot_id": shot_id, "status": "failed", "message": message, "fix": fix}
