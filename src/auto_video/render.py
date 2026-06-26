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
