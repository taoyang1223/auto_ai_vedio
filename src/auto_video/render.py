from __future__ import annotations

import subprocess
import shutil
import json
from pathlib import Path
from typing import Any, Protocol

from .errors import RenderError
from .manifest import ManifestStore
from .models import Project
from .project import resolve_project_path
from .jobs import utc_now_iso
from .shot_policy import selected_clip_for_shot


class RenderRunner(Protocol):
    def run(self, command: tuple[str, ...]) -> None:
        """Run a render command or raise a user-facing error."""


class SubprocessRenderRunner:
    def run(self, command: tuple[str, ...]) -> None:
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise RenderError("missing command 'ffmpeg'", fix="Install ffmpeg to assemble the final video.") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise RenderError("ffmpeg failed while assembling final video", fix=stderr or "Check clip codecs.") from exc


def build_render_plan(project: Project) -> dict:
    shots = []
    manifest_shots = project.manifest.get("shots", {})
    has_audio = False
    for shot in project.shots:
        entry = manifest_shots.get(shot.id, {})
        clip, source_clip, lipsync_clip, use_lipsync = selected_clip_for_shot(shot, entry)
        if not clip:
            raise RenderError(
                f"shot {shot.id} has no generated clip in manifest",
                fix="Run auto-video generate before assemble, or use assemble --dry-run before requiring media.",
            )
        audio = entry.get("audio")
        clip_path = resolve_project_path(project.config.root, str(clip))
        audio_path = resolve_project_path(project.config.root, str(audio)) if audio else None
        has_audio = has_audio or bool(audio)
        media_duration = _media_duration_seconds(clip_path)
        render_duration = round(media_duration, 3) if media_duration else shot.duration
        shots.append(
            {
                "id": shot.id,
                "clip": str(clip),
                "source_clip": str(source_clip) if source_clip else None,
                "lipsync_clip": str(lipsync_clip) if lipsync_clip else None,
                "use_lipsync": use_lipsync,
                "clip_path": clip_path.as_posix(),
                "duration": render_duration,
                "planned_duration": shot.duration,
                "media_duration": media_duration,
                "subtitle": shot.subtitle,
                "exists": clip_path.exists(),
                "bytes": clip_path.stat().st_size if clip_path.exists() else 0,
                "audio": str(audio) if audio else None,
                "audio_path": audio_path.as_posix() if audio_path else None,
                "audio_exists": audio_path.exists() if audio_path else False,
                "audio_bytes": audio_path.stat().st_size if audio_path and audio_path.exists() else 0,
            }
        )
    output = "renders/final.mp4"
    concat_file = "renders/final.concat.txt"
    subtitle_file = "renders/final.srt"
    voice_file = "renders/final_voice.wav"
    voice_concat_file = "renders/final_voice.concat.txt"
    voice_segment_dir = "renders/audio_segments"
    output_path = (project.config.root / output).as_posix()
    concat_path = (project.config.root / concat_file).as_posix()
    subtitle_path = (project.config.root / subtitle_file).as_posix()
    voice_path = (project.config.root / voice_file).as_posix()
    voice_concat_path = (project.config.root / voice_concat_file).as_posix()
    ffmpeg = ["ffmpeg", "-y"]
    ffmpeg.extend(["-f", "concat", "-safe", "0", "-i", concat_path, "-c", "copy", output_path])
    audio = {
        "enabled": has_audio,
        "output": voice_file,
        "output_path": voice_path,
        "concat_file": voice_concat_file,
        "concat_path": voice_concat_path,
        "segment_dir": voice_segment_dir,
        "sample_rate": 48000,
        "channels": 2,
    }
    return {
        "output": output,
        "output_path": output_path,
        "concat_file": concat_file,
        "concat_path": concat_path,
        "subtitle_file": subtitle_file,
        "subtitle_path": subtitle_path,
        "width": project.config.width,
        "height": project.config.height,
        "fps": project.config.fps,
        "transition": {
            "type": project.config.render.transition.type,
            "duration": project.config.render.transition.duration,
        },
        "audio": audio,
        "shots": shots,
        "ffmpeg": ffmpeg,
    }


def assemble_project(
    project: Project,
    *,
    dry_run: bool = False,
    runner: RenderRunner | None = None,
) -> dict[str, Any]:
    plan = build_render_plan(project)
    checks = _quality_checks(plan)
    result = {"dry_run": dry_run, **plan, "checks": checks}
    if dry_run:
        return result
    failed = [check for check in checks if check["status"] == "failed"]
    if failed:
        first = failed[0]
        raise RenderError(first["message"], fix=first.get("fix", "Fix render input checks and retry."))

    root = project.config.root
    output = resolve_project_path(root, str(plan["output"]))
    concat_file = resolve_project_path(root, str(plan["concat_file"]))
    subtitle_file = resolve_project_path(root, str(plan["subtitle_file"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    concat_file.parent.mkdir(parents=True, exist_ok=True)
    archived = _archive_existing_render(root, output)
    _write_concat_file(project.config.root, plan, concat_file)
    subtitle = _write_subtitle_file(root, plan, subtitle_file)
    command = tuple(str(part) for part in plan["ffmpeg"])
    (runner or SubprocessRenderRunner()).run(command)
    if not output.exists() or output.stat().st_size == 0:
        raise RenderError(
            f"render output {plan['output']} was not created",
            fix="Check ffmpeg output and clip compatibility.",
        )
    runner = runner or SubprocessRenderRunner()
    voiceover = None
    if plan["audio"]["enabled"]:
        voiceover = _assemble_voiceover(root, plan, output, runner)
        command = tuple(voiceover["mux_command"])
    _record_render(project, output, command, archived=archived, subtitle=subtitle, voiceover=voiceover)
    return {
        **result,
        "status": "succeeded",
        "bytes": output.stat().st_size,
        "archived": archived,
        "subtitle": subtitle,
        "voiceover": voiceover,
    }


def _quality_checks(plan: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for shot in plan["shots"]:
        if not shot["exists"]:
            checks.append(
                {
                    "name": "clip_exists",
                    "shot_id": shot["id"],
                    "status": "failed",
                    "message": f"clip {shot['clip']} is missing",
                    "fix": "Regenerate the shot before assembling.",
                }
            )
            continue
        if int(shot["bytes"]) <= 0:
            checks.append(
                {
                    "name": "clip_nonempty",
                    "shot_id": shot["id"],
                    "status": "failed",
                    "message": f"clip {shot['clip']} is empty",
                    "fix": "Regenerate the shot before assembling.",
                }
            )
            continue
        checks.append(
            {
                "name": "clip_ready",
                "shot_id": shot["id"],
                "status": "ok",
                "message": f"clip {shot['clip']} is ready",
                "bytes": shot["bytes"],
            }
        )
        if shot.get("media_duration") and float(shot.get("planned_duration") or 0) > 0:
            ratio = float(shot["media_duration"]) / float(shot["planned_duration"])
            if ratio < 0.75:
                checks.append(
                    {
                        "name": "clip_duration_short",
                        "shot_id": shot["id"],
                        "status": "warning",
                        "message": (
                            f"clip {shot['clip']} is {float(shot['media_duration']):.2f}s, "
                            f"planned {float(shot['planned_duration']):.2f}s"
                        ),
                        "fix": "短对白镜头可以接受；若这是旁白或空镜，请重生成视频或检查是否误用了口型同步版本。",
                    }
                )
        if shot.get("audio") and not shot.get("audio_exists"):
            checks.append(
                {
                    "name": "audio_exists",
                    "shot_id": shot["id"],
                    "status": "failed",
                    "message": f"audio {shot['audio']} is missing",
                    "fix": "Regenerate the voiceover before assembling.",
                }
            )
        elif shot.get("audio"):
            checks.append(
                {
                    "name": "audio_ready",
                    "shot_id": shot["id"],
                    "status": "ok",
                    "message": f"audio {shot['audio']} is ready",
                    "bytes": shot["audio_bytes"],
                }
            )
    return checks


def _write_concat_file(project_root: Path, plan: dict[str, Any], concat_file: Path) -> None:
    lines = []
    for shot in plan["shots"]:
        path = resolve_project_path(project_root, str(shot["clip"]))
        lines.append(f"file '{path.as_posix()}'")
    concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _media_duration_seconds(path: Path) -> float | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                path.as_posix(),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if completed.returncode != 0:
        return None
    try:
        value = json.loads(completed.stdout or "{}").get("format", {}).get("duration")
        duration = float(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return duration if duration > 0 else None


def _assemble_voiceover(root: Path, plan: dict[str, Any], output: Path, runner: RenderRunner) -> dict[str, Any]:
    audio = plan["audio"]
    segment_dir = resolve_project_path(root, str(audio["segment_dir"]))
    voice_file = resolve_project_path(root, str(audio["output"]))
    concat_file = resolve_project_path(root, str(audio["concat_file"]))
    temp_output = output.with_name(f"{output.stem}.with_audio{output.suffix}")
    segment_dir.mkdir(parents=True, exist_ok=True)
    voice_file.parent.mkdir(parents=True, exist_ok=True)
    commands: list[tuple[str, ...]] = []
    segments = []
    for shot in plan["shots"]:
        segment = segment_dir / f"{shot['id']}.wav"
        if shot.get("audio_path"):
            command = _normalize_audio_command(Path(str(shot["audio_path"])), segment, float(shot.get("duration") or 0), audio)
            source = shot["audio"]
        else:
            command = _silence_audio_command(segment, float(shot.get("duration") or 0), audio)
            source = None
        runner.run(command)
        commands.append(command)
        segments.append({"shot_id": shot["id"], "path": _relative(root, segment), "source": source})

    lines = [f"file '{(root / item['path']).resolve().as_posix()}'" for item in segments]
    concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    concat_command = (
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        concat_file.as_posix(),
        "-c",
        "copy",
        voice_file.as_posix(),
    )
    runner.run(concat_command)
    commands.append(concat_command)

    mux_command = (
        "ffmpeg",
        "-y",
        "-i",
        output.as_posix(),
        "-i",
        voice_file.as_posix(),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        temp_output.as_posix(),
    )
    runner.run(mux_command)
    commands.append(mux_command)
    if not temp_output.exists() or temp_output.stat().st_size == 0:
        raise RenderError(
            f"render output {temp_output.as_posix()} was not created",
            fix="Check ffmpeg audio mux output.",
        )
    temp_output.replace(output)
    return {
        "path": _relative(root, voice_file),
        "concat_file": _relative(root, concat_file),
        "segments": segments,
        "commands": [list(command) for command in commands],
        "mux_command": list(mux_command),
    }


def _normalize_audio_command(input_path: Path, output_path: Path, duration: float, audio: dict[str, Any]) -> tuple[str, ...]:
    command = ("ffmpeg", "-y", "-i", input_path.as_posix())
    if duration > 0:
        command = (*command, "-filter:a", f"apad=whole_dur={duration:.3f},atrim=0:{duration:.3f}")
    return (
        *command,
        "-ar",
        str(audio["sample_rate"]),
        "-ac",
        str(audio["channels"]),
        output_path.as_posix(),
    )


def _silence_audio_command(output_path: Path, duration: float, audio: dict[str, Any]) -> tuple[str, ...]:
    channel_layout = "mono" if int(audio["channels"]) == 1 else "stereo"
    return (
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={audio['sample_rate']}:cl={channel_layout}",
        "-t",
        f"{max(0.2, duration):.3f}",
        "-ar",
        str(audio["sample_rate"]),
        "-ac",
        str(audio["channels"]),
        output_path.as_posix(),
    )


def _write_subtitle_file(project_root: Path, plan: dict[str, Any], subtitle_file: Path) -> dict[str, Any] | None:
    entries = []
    cursor = 0.0
    for shot in plan["shots"]:
        text = str(shot.get("subtitle") or "").strip()
        start = cursor
        end = cursor + float(shot.get("duration") or 0)
        cursor = end
        if text:
            entries.append((start, end, text))
    if not entries:
        subtitle_file.unlink(missing_ok=True)
        return None
    subtitle_file.parent.mkdir(parents=True, exist_ok=True)
    blocks = []
    for index, (start, end, text) in enumerate(entries, start=1):
        blocks.append(f"{index}\n{_srt_timestamp(start)} --> {_srt_timestamp(end)}\n{text}\n")
    subtitle_file.write_text("\n".join(blocks), encoding="utf-8")
    return {"path": _relative(project_root, subtitle_file), "entries": len(entries)}


def _srt_timestamp(value: float) -> str:
    total_ms = max(0, round(value * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def _archive_existing_render(project_root: Path, output: Path) -> dict[str, Any] | None:
    if not output.exists() or output.stat().st_size <= 0:
        return None
    stamp = utc_now_iso().replace(":", "").replace("-", "").replace("Z", "Z")
    archive = project_root / "renders" / "versions" / f"{output.stem}_{stamp}{output.suffix}"
    archive.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output, archive)
    return {
        "path": _relative(project_root, archive),
        "archived_at": utc_now_iso(),
        "bytes": archive.stat().st_size,
    }


def _record_render(
    project: Project,
    output: Path,
    command: tuple[str, ...],
    *,
    archived: dict[str, Any] | None = None,
    subtitle: dict[str, Any] | None = None,
    voiceover: dict[str, Any] | None = None,
) -> None:
    store = ManifestStore(project.config.root / "manifest.json", project_name=project.config.name)
    previous = store.data["renders"].get("final")
    versions = []
    if isinstance(previous, dict) and isinstance(previous.get("versions"), list):
        versions = list(previous["versions"])
    if archived:
        versions.append(archived)
    store.data["renders"]["final"] = {
        "status": "generated",
        "path": store._relative(output),
        "command": list(command),
    }
    if subtitle:
        store.data["renders"]["final"]["subtitle"] = subtitle["path"]
        store.data["renders"]["final"]["subtitle_entries"] = subtitle["entries"]
    if voiceover:
        store.data["renders"]["final"]["voiceover"] = voiceover["path"]
        store.data["renders"]["final"]["voiceover_segments"] = len(voiceover["segments"])
    if versions:
        store.data["renders"]["final"]["versions"] = versions
    store.save()


def _relative(root: Path, value: Path) -> str:
    try:
        return value.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return value.as_posix()
