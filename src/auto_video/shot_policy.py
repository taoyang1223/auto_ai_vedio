from __future__ import annotations

from typing import Any


NARRATOR_SPEAKERS = {"narrator", "旁白", "voiceover", "narration"}


def shot_needs_lipsync(shot: Any) -> bool:
    speaker = str(getattr(shot, "speaker", "") or "").strip()
    if not speaker:
        return True
    return speaker.casefold() not in NARRATOR_SPEAKERS and speaker not in NARRATOR_SPEAKERS


def selected_clip_for_shot(shot: Any, manifest_entry: dict[str, Any]) -> tuple[str | None, str | None, str | None, bool]:
    source_clip = str(manifest_entry.get("clip") or "") or None
    lipsync_clip = str(manifest_entry.get("lipsync_clip") or "") or None
    use_lipsync = bool(lipsync_clip and shot_needs_lipsync(shot))
    clip = lipsync_clip if use_lipsync else source_clip or lipsync_clip
    return clip, source_clip, lipsync_clip, use_lipsync
