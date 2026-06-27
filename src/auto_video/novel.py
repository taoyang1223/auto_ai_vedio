from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .jobs import utc_now_iso
from .models import Project
from .project import load_project
from .validation import validate_project

NOVEL_FILE = "novel.json"
MAX_CHAPTER_CHARS = 120_000
MAX_NOVEL_SHOTS = 180
DEFAULT_TARGET_MINUTES = 20.0
DEFAULT_SHOT_SECONDS = 12.0
BASE_NEGATIVE = "text, watermark, logo, bad hands, extra fingers, distorted body, low quality, blurry, identity drift"

NARRATOR_ID = "narrator"
NARRATOR_NAME = "旁白"
FEMALE_VOICES = ("zh-CN-XiaoxiaoNeural", "zh-CN-XiaoyiNeural", "zh-CN-liaoning-XiaobeiNeural")
MALE_VOICES = ("zh-CN-YunxiNeural", "zh-CN-YunjianNeural", "zh-CN-YunyangNeural")
NEUTRAL_VOICES = ("zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural", "zh-CN-XiaoyiNeural", "zh-CN-YunjianNeural")

NAME_STOPWORDS = {
    "这个",
    "那个",
    "他们",
    "她们",
    "我们",
    "你们",
    "自己",
    "众人",
    "男人",
    "女人",
    "少年",
    "少女",
    "老人",
    "时候",
    "声音",
    "眼前",
    "突然",
    "终于",
    "只是",
}


def load_novel_store(root: str | Path) -> dict[str, Any]:
    path = Path(root) / NOVEL_FILE
    if not path.exists():
        return _empty_store()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError("novel.json must contain an object", fix="请恢复有效的小说生产配置。")
    store = _empty_store()
    store.update(data)
    store["characters"] = _clean_list(data.get("characters"))
    store["scenes"] = _clean_list(data.get("scenes"))
    store["chapters"] = _clean_list(data.get("chapters"))
    return store


def draft_novel_chapter(project: Project, payload: dict[str, Any]) -> dict[str, Any]:
    chapter_text = _normalize_chapter(str(payload.get("chapter_text") or payload.get("script") or ""))
    if not chapter_text:
        raise ConfigError("章节内容不能为空", fix="请粘贴本章小说正文。")
    if len(chapter_text) > MAX_CHAPTER_CHARS:
        raise ConfigError("章节内容过长", fix=f"请把单章正文控制在 {MAX_CHAPTER_CHARS} 字以内，或拆成上下集。")

    target_minutes = _bounded_float(payload.get("target_minutes"), default=DEFAULT_TARGET_MINUTES, minimum=1, maximum=60)
    preferred_shot_seconds = _bounded_float(payload.get("shot_seconds"), default=DEFAULT_SHOT_SECONDS, minimum=4, maximum=30)
    target_seconds = target_minutes * 60
    shot_count = _target_shot_count(chapter_text, target_seconds, preferred_shot_seconds)
    shot_seconds = round(target_seconds / shot_count, 2)
    provider = str(payload.get("provider") or project.config.default_video_provider).strip()

    store = load_novel_store(project.config.root)
    characters = _merge_characters(store.get("characters", []), chapter_text)
    scenes = _merge_scenes(store.get("scenes", []), chapter_text)
    beats = _beats_for_count(chapter_text, shot_count)
    shots = [
        _shot_payload(
            project,
            beat=beat,
            index=index,
            total=shot_count,
            duration=shot_seconds,
            provider=provider,
            characters=characters,
            scenes=scenes,
        )
        for index, beat in enumerate(beats)
    ]
    chapter_id = _chapter_id(store, payload)
    chapter = {
        "id": chapter_id,
        "title": str(payload.get("title") or f"第{len(store.get('chapters', [])) + 1}章").strip(),
        "target_minutes": target_minutes,
        "duration": round(sum(float(shot["duration"]) for shot in shots), 2),
        "shot_count": len(shots),
        "source_chars": len(chapter_text),
        "created_at": utc_now_iso(),
    }
    next_store = {
        **store,
        "characters": characters,
        "scenes": scenes,
        "chapters": [*store.get("chapters", []), chapter],
    }
    return {
        "chapter": chapter,
        "characters": characters,
        "scenes": scenes,
        "shots": shots,
        "meta": {
            "target_minutes": target_minutes,
            "duration": chapter["duration"],
            "shot_count": len(shots),
            "shot_seconds": shot_seconds,
            "provider": provider,
        },
        "novel": next_store,
    }


def apply_novel_chapter(root: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    root = Path(root).resolve()
    draft = payload.get("draft") if isinstance(payload.get("draft"), dict) else None
    if draft is None:
        draft = draft_novel_chapter(load_project(root), payload)
    shots = draft.get("shots")
    novel = draft.get("novel")
    if not isinstance(shots, list) or not shots:
        raise ConfigError("章节分镜为空", fix="请先生成章节生产草稿。")
    if not isinstance(novel, dict):
        raise ConfigError("章节人物/场景数据为空", fix="请重新生成章节生产草稿。")

    old_shots = (root / "shots.json").read_text(encoding="utf-8") if (root / "shots.json").exists() else ""
    old_novel = (root / NOVEL_FILE).read_text(encoding="utf-8") if (root / NOVEL_FILE).exists() else None
    old_manifest = (root / "manifest.json").read_text(encoding="utf-8") if (root / "manifest.json").exists() else None
    try:
        _write_identity_assets(root, novel)
        _write_json(root / "shots.json", {"shots": shots})
        _write_json(root / NOVEL_FILE, novel)
        if bool(payload.get("reset_manifest", True)):
            _reset_generation_manifest(root)
        validate_project(load_project(root))
    except Exception:
        if old_shots:
            (root / "shots.json").write_text(old_shots, encoding="utf-8")
        if old_novel is None:
            (root / NOVEL_FILE).unlink(missing_ok=True)
        else:
            (root / NOVEL_FILE).write_text(old_novel, encoding="utf-8")
        if old_manifest is None:
            (root / "manifest.json").unlink(missing_ok=True)
        else:
            (root / "manifest.json").write_text(old_manifest, encoding="utf-8")
        raise
    return {
        "applied": len(shots),
        "chapter": draft.get("chapter", {}),
        "characters": novel.get("characters", []),
        "scenes": novel.get("scenes", []),
    }


def _empty_store() -> dict[str, Any]:
    return {"schema_version": "0.1", "characters": [], "scenes": [], "chapters": []}


def _clean_list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value] if isinstance(value, list) else []


def _normalize_chapter(value: str) -> str:
    lines = [line.strip() for line in value.replace("\u3000", " ").splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _bounded_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    if result < minimum or result > maximum:
        raise ConfigError("章节生产参数超出范围", fix=f"请填写 {minimum:g} 到 {maximum:g} 之间的数值。")
    return round(result, 2)


def _target_shot_count(text: str, target_seconds: float, preferred_shot_seconds: float) -> int:
    duration_count = math.ceil(target_seconds / preferred_shot_seconds)
    text_count = math.ceil(len(text) / 58)
    return max(1, min(MAX_NOVEL_SHOTS, max(duration_count, text_count)))


def _merge_characters(existing: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    by_name = {str(item.get("name")): dict(item) for item in existing if item.get("name")}
    if NARRATOR_NAME not in by_name:
        by_name[NARRATOR_NAME] = _character_payload(NARRATOR_NAME, len(by_name), gender="neutral", character_id=NARRATOR_ID)
    for name in _candidate_names(text):
        if name in by_name:
            continue
        gender = _infer_gender(name, text)
        by_name[name] = _character_payload(name, len(by_name), gender=gender)
    return list(by_name.values())


def _candidate_names(text: str) -> list[str]:
    candidates: list[str] = []
    patterns = [
        r"([\u4e00-\u9fff]{2,4})(?:说|问|道|喊|叫|笑|看|走|站|坐|想|叹|点头|摇头)",
        r"(?:叫做|名叫|唤作)([\u4e00-\u9fff]{2,4})",
        r"“[^”]{1,60}”([\u4e00-\u9fff]{2,4})(?:说|问|道)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            name = match.group(1).strip()
            if _is_probable_name(name) and name not in candidates:
                candidates.append(name)
    return candidates[:24]


def _is_probable_name(value: str) -> bool:
    if value in NAME_STOPWORDS or len(value) < 2 or len(value) > 4:
        return False
    if any(word in value for word in NAME_STOPWORDS):
        return False
    return bool(re.fullmatch(r"[\u4e00-\u9fff]+", value))


def _infer_gender(name: str, text: str) -> str:
    window = _near_text(name, text)
    if re.search(r"她|姑娘|小姐|女子|少女|夫人|女", window):
        return "female"
    if re.search(r"他|公子|先生|男子|少年|男", window):
        return "male"
    return "neutral"


def _near_text(name: str, text: str) -> str:
    index = text.find(name)
    if index < 0:
        return ""
    return text[max(0, index - 80) : index + 120]


def _character_payload(name: str, index: int, *, gender: str, character_id: str | None = None) -> dict[str, Any]:
    voice_pool = FEMALE_VOICES if gender == "female" else MALE_VOICES if gender == "male" else NEUTRAL_VOICES
    return {
        "id": character_id or _safe_id("char", name),
        "name": name,
        "gender": gender,
        "visual_profile": _visual_profile(name, index, gender),
        "voice": voice_pool[index % len(voice_pool)],
        "voice_profile": _voice_profile(index, gender),
        "aliases": [name],
    }


def _visual_profile(name: str, index: int, gender: str) -> str:
    palettes = ("墨青", "银灰", "深红", "月白", "黛蓝", "松绿", "金棕", "紫黑")
    builds = ("清瘦", "挺拔", "沉稳", "敏捷", "温和", "冷峻")
    hair = "长发" if gender == "female" else "短发" if gender == "male" else "自然发型"
    return f"{name}：{builds[index % len(builds)]}体态，{hair}，{palettes[index % len(palettes)]}色系服装，五官和服饰在所有章节保持一致"


def _voice_profile(index: int, gender: str) -> str:
    tone = ("沉稳", "清亮", "低缓", "温和", "紧张", "冷静")[index % 6]
    return f"{gender} voice, {tone} tone, consistent timbre across chapters"


def _merge_scenes(existing: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    by_name = {str(item.get("name")): dict(item) for item in existing if item.get("name")}
    for name in _candidate_scenes(text):
        if name not in by_name:
            by_name[name] = _scene_payload(name, len(by_name))
    if not by_name:
        by_name["本章主要场景"] = _scene_payload("本章主要场景", 0)
    return list(by_name.values())


def _candidate_scenes(text: str) -> list[str]:
    candidates: list[str] = []
    for pattern in (r"(?:在|来到|回到|进入|走进)([\u4e00-\u9fff]{2,14})", r"([\u4e00-\u9fff]{2,10})(?:中|里|内|外)，"):
        for match in re.finditer(pattern, text):
            name = match.group(1).strip(" ，。！？；、")
            if len(name) >= 2 and name not in NAME_STOPWORDS and name not in candidates:
                candidates.append(name)
    return candidates[:16]


def _scene_payload(name: str, index: int) -> dict[str, Any]:
    moods = ("冷色月光", "暖色烛火", "晨雾微光", "雨夜反光", "尘埃逆光", "幽暗高反差")
    return {
        "id": _safe_id("scene", name),
        "name": name,
        "style_prompt": f"{name}，{moods[index % len(moods)]}，空间结构、材质、色调在后续章节保持一致",
        "lighting": moods[index % len(moods)],
        "continuity": "same geography, same props placement, same atmosphere and color palette",
    }


def _beats_for_count(text: str, count: int) -> list[str]:
    sentences = [_clean_segment(part) for part in re.split(r"(?<=[。！？!?；;])|\n+", text) if _clean_segment(part)]
    if not sentences:
        sentences = [_clean_segment(text)]
    target_chars = max(18, math.ceil(len(text) / count))
    beats: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > target_chars and len(beats) < count - 1:
            beats.append(current)
            current = sentence
        else:
            current = f"{current}{sentence}" if current else sentence
    if current:
        beats.append(current)
    while len(beats) < count:
        beats.append(beats[-1])
    if len(beats) > count:
        tail = "".join(beats[count - 1 :])
        beats = [*beats[: count - 1], tail]
    return [_truncate(beat, 220) for beat in beats]


def _shot_payload(
    project: Project,
    *,
    beat: str,
    index: int,
    total: int,
    duration: float,
    provider: str,
    characters: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
) -> dict[str, Any]:
    speaker = _speaker_for_beat(beat, characters)
    scene = _scene_for_beat(beat, scenes)
    visible = _visible_characters(beat, characters, speaker)
    character_lines = [str(item.get("visual_profile") or item.get("name")) for item in visible]
    scene_line = str(scene.get("style_prompt") or scene.get("name"))
    dialogue_cue = "口型与配音台词同步，表情随语气变化" if speaker.get("id") != NARRATOR_ID else "人物动作与旁白节奏同步，场景细节跟随叙事变化"
    return {
        "id": f"S{index + 1:03d}",
        "title": f"第{index + 1:03d}镜 · {_truncate(beat, 16)}",
        "duration": duration,
        "intent": beat,
        "provider": provider,
        "characters": [str(item.get("id")) for item in visible],
        "scene": str(scene.get("id") or ""),
        "speaker": str(speaker.get("id") or NARRATOR_ID),
        "voice": str(speaker.get("voice") or NEUTRAL_VOICES[0]),
        "visual_prompt": (
            f"原创小说章节镜头，{project.config.aspect_ratio}，场景：{scene_line}。"
            f"人物：{'；'.join(character_lines)}。剧情：{beat}。"
            "电影感叙事画面，角色外形严格一致，场景风格严格一致，动作自然连贯"
        ),
        "camera_motion": _camera_for_index(index, total),
        "environment_motion": f"{scene.get('name')}内的光影、风、尘埃或道具随旁白节奏轻微运动",
        "performance": f"{speaker.get('name')}作为当前声音焦点；{dialogue_cue}",
        "lighting": str(scene.get("lighting") or "cinematic soft light"),
        "audio_intent": f"说话人={speaker.get('name')}，音色={speaker.get('voice_profile')}，旁白/对白与画面动作同步",
        "subtitle": beat,
        "negative_prompt": BASE_NEGATIVE,
        "refs": _refs_for_shot(visible, scene),
    }


def _speaker_for_beat(beat: str, characters: list[dict[str, Any]]) -> dict[str, Any]:
    for character in characters:
        name = str(character.get("name") or "")
        if name and re.search(re.escape(name) + r"(?:说|问|道|喊|叫|笑|叹)", beat):
            return character
    for character in characters:
        name = str(character.get("name") or "")
        if name and name != NARRATOR_NAME and name in beat:
            return character
    return characters[0]


def _scene_for_beat(beat: str, scenes: list[dict[str, Any]]) -> dict[str, Any]:
    for scene in scenes:
        name = str(scene.get("name") or "")
        if name and name in beat:
            return scene
    return scenes[0]


def _visible_characters(beat: str, characters: list[dict[str, Any]], speaker: dict[str, Any]) -> list[dict[str, Any]]:
    visible = [item for item in characters if item.get("id") != NARRATOR_ID and str(item.get("name") or "") in beat]
    if speaker.get("id") != NARRATOR_ID and speaker not in visible:
        visible.insert(0, speaker)
    return visible[:3] or [item for item in characters if item.get("id") != NARRATOR_ID][:1] or [characters[0]]


def _refs_for_shot(characters: list[dict[str, Any]], scene: dict[str, Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for character in characters:
        refs.append(
            {
                "path": f"assets/novel/characters/{character['id']}.txt",
                "type": "text",
                "role": "style_reference",
                "usage": "preserve_subject",
            }
        )
        refs.append(
            {
                "path": f"assets/novel/voices/{character['id']}.txt",
                "type": "text",
                "role": "voice_reference",
                "usage": "preserve_voice",
            }
        )
    refs.append(
        {
            "path": f"assets/novel/scenes/{scene['id']}.txt",
            "type": "text",
            "role": "environment_reference",
            "usage": "provide_context",
        }
    )
    return refs


def _camera_for_index(index: int, total: int) -> str:
    presets = (
        "缓慢推进，建立人物与场景关系",
        "中景跟拍，保持角色口型和表情可见",
        "轻微横移，交代动作与空间",
        "近景停留，突出表情变化",
        "稳定广角，展示场景与人物调度",
    )
    if index == 0:
        return presets[0]
    if index == total - 1:
        return "缓慢拉远，形成章节收束"
    return presets[index % len(presets)]


def _write_identity_assets(root: Path, novel: dict[str, Any]) -> None:
    for character in novel.get("characters", []):
        if not isinstance(character, dict):
            continue
        character_id = str(character.get("id") or _safe_id("char", str(character.get("name") or "character")))
        _write_text_asset(
            root / "assets" / "novel" / "characters" / f"{character_id}.txt",
            "\n".join(
                [
                    f"name: {character.get('name')}",
                    f"gender: {character.get('gender')}",
                    f"visual_profile: {character.get('visual_profile')}",
                    f"aliases: {', '.join(character.get('aliases', [])) if isinstance(character.get('aliases'), list) else ''}",
                ]
            ),
        )
        _write_text_asset(
            root / "assets" / "novel" / "voices" / f"{character_id}.txt",
            "\n".join(
                [
                    f"name: {character.get('name')}",
                    f"voice: {character.get('voice')}",
                    f"voice_profile: {character.get('voice_profile')}",
                ]
            ),
        )
    for scene in novel.get("scenes", []):
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("id") or _safe_id("scene", str(scene.get("name") or "scene")))
        _write_text_asset(
            root / "assets" / "novel" / "scenes" / f"{scene_id}.txt",
            "\n".join(
                [
                    f"name: {scene.get('name')}",
                    f"style_prompt: {scene.get('style_prompt')}",
                    f"lighting: {scene.get('lighting')}",
                    f"continuity: {scene.get('continuity')}",
                ]
            ),
        )


def _write_text_asset(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _reset_generation_manifest(root: Path) -> None:
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        data = {}
    data["shots"] = {}
    data["renders"] = {}
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _chapter_id(store: dict[str, Any], payload: dict[str, Any]) -> str:
    raw = str(payload.get("chapter_id") or "").strip()
    if raw:
        return _safe_id("chapter", raw)
    return f"chapter_{len(store.get('chapters', [])) + 1:03d}"


def _safe_id(prefix: str, value: str) -> str:
    encoded = "_".join(f"{ord(char):x}" for char in value.strip()[:12])
    return f"{prefix}_{encoded or 'item'}"


def _clean_segment(value: str) -> str:
    return value.strip(" \t\r\n，,。.!！?？；;：:、")


def _truncate(value: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"
