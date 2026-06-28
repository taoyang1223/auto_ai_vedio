from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .jobs import utc_now_iso
from .models import Project
from .novel_analyzer import analyze_novel_with_codex
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
    "或者",
    "那里",
    "这里",
    "手里",
    "视野",
    "床边",
    "他手里",
    "她手里",
}

SCENE_FALSE_POSITIVES = {
    "他手里",
    "她手里",
    "视野里",
    "视野里缓慢聚焦",
    "冷色月光",
    "暖色烛火",
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
    analysis = analyze_novel_with_codex(
        analyzer=str(payload.get("analyzer") or ""),
        chapter_text=chapter_text,
        existing_store=store,
        project_root=Path(project.config.root),
        provider=provider,
        shot_count=shot_count,
        target_minutes=target_minutes,
    )
    if analysis.data:
        characters = _merge_analyzed_characters(store.get("characters", []), analysis.data.get("characters", []), chapter_text)
        scenes = _merge_analyzed_scenes(store.get("scenes", []), analysis.data.get("scenes", []), chapter_text)
        beats = _beats_from_analysis(analysis.data, chapter_text, shot_count)
    else:
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
            "analyzer": analysis.source,
            "analyzer_error": analysis.error,
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


def _clean_text(value: Any, *, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "").replace("\u3000", " ")).strip()
    text = text.strip(" \t\r\n，,。.!！?？；;：:、")
    return _truncate(text, limit) if limit else text


def _clean_entity_name(value: Any) -> str:
    text = _clean_text(value, limit=40)
    text = text.strip("“”\"'「」『』（）()[]【】")
    text = re.sub(r"^(?:一个|一名|一位|这位|那位|那个|这个)", "", text)
    text = text.replace("床边的", "床边").replace("陌生的", "陌生")
    return text.strip(" 的")


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _normalize_gender(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"male", "man", "男性", "男"}:
        return "male"
    if raw in {"female", "woman", "女性", "女"}:
        return "female"
    if raw in {"neutral", "unknown", "旁白", "中性", "未知"}:
        return "neutral"
    return ""


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
    return [_normalize_character(item, index) for index, item in enumerate(by_name.values())]


def _merge_analyzed_characters(existing: list[dict[str, Any]], analyzed: Any, text: str) -> list[dict[str, Any]]:
    by_name = {str(item.get("name")): dict(item) for item in existing if item.get("name")}
    if NARRATOR_NAME not in by_name:
        by_name[NARRATOR_NAME] = _character_payload(NARRATOR_NAME, len(by_name), gender="neutral", character_id=NARRATOR_ID)
    if isinstance(analyzed, list):
        for item in analyzed:
            if not isinstance(item, dict):
                continue
            name = _clean_entity_name(item.get("name"))
            if not _is_valid_analyzed_character_name(name):
                continue
            if name in by_name:
                continue
            gender = _normalize_gender(item.get("gender")) or _infer_gender(name, text)
            payload = _character_payload(name, len(by_name), gender=gender)
            for key in ("visual_profile", "wardrobe_profile", "voice_profile"):
                value = _clean_text(item.get(key), limit=420)
                if value:
                    payload[key] = value
            aliases = [_clean_entity_name(alias) for alias in item.get("aliases", [])] if isinstance(item.get("aliases"), list) else []
            aliases = [alias for alias in aliases if alias and alias not in NAME_STOPWORDS]
            payload["aliases"] = _dedupe([name, *aliases])
            by_name[name] = payload
    if len(by_name) <= 1:
        return _merge_characters(existing, text)
    return [_normalize_character(item, index) for index, item in enumerate(by_name.values())]


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


def _is_valid_analyzed_character_name(value: str) -> bool:
    if not value or len(value) < 2 or len(value) > 12:
        return False
    if value in NAME_STOPWORDS or value in SCENE_FALSE_POSITIVES:
        return False
    if re.search(r"(或者|然后|于是|突然|终于|只是|视野|手里|眼神|声音|时候|这里|那里)", value):
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]", value))


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
        "wardrobe_profile": _wardrobe_profile(name, index, gender),
        "voice": voice_pool[index % len(voice_pool)],
        "voice_profile": _voice_profile(index, gender),
        "aliases": [name],
    }


def _normalize_character(item: dict[str, Any], index: int) -> dict[str, Any]:
    name = str(item.get("name") or f"角色{index + 1}")
    gender = str(item.get("gender") or "neutral")
    defaults = _character_payload(
        name,
        index,
        gender=gender,
        character_id=str(item.get("id") or "") or None,
    )
    merged = {**defaults, **item}
    for key, value in defaults.items():
        if not merged.get(key):
            merged[key] = value
    if not isinstance(merged.get("aliases"), list):
        merged["aliases"] = [name]
    return merged


def _visual_profile(name: str, index: int, gender: str) -> str:
    palettes = ("墨青", "银灰", "深红", "月白", "黛蓝", "松绿", "金棕", "紫黑")
    builds = ("清瘦", "挺拔", "沉稳", "敏捷", "温和", "冷峻")
    hair = "长发" if gender == "female" else "短发" if gender == "male" else "自然发型"
    return f"{name}：{builds[index % len(builds)]}体态，{hair}，{palettes[index % len(palettes)]}识别色，五官、发型和体态在所有章节保持一致"


def _wardrobe_profile(name: str, index: int, gender: str) -> str:
    palettes = ("墨青", "银灰", "深红", "月白", "黛蓝", "松绿", "金棕", "紫黑")
    silhouettes = {
        "female": ("修身长衫", "轻便披帛", "窄袖劲装"),
        "male": ("利落短袍", "束腰长衣", "窄袖外袍"),
        "neutral": ("简洁常服", "低调外袍", "素色披风"),
    }
    props = ("银色发簪", "旧皮护腕", "细绳腰封", "暗纹衣领", "小型随身包", "磨旧披肩")
    pool = silhouettes.get(gender, silhouettes["neutral"])
    return (
        f"{name}基础服装：{palettes[index % len(palettes)]}主识别色，"
        f"{pool[index % len(pool)]}轮廓，固定识别物为{props[index % len(props)]}；"
        "后续可按场景增减雨具、斗篷、礼服或护具，但必须保留主识别色、轮廓和识别物"
    )


def _voice_profile(index: int, gender: str) -> str:
    tone = ("沉稳", "清亮", "低缓", "温和", "紧张", "冷静")[index % 6]
    return f"{gender} voice, {tone} tone, consistent timbre across chapters"


def _merge_scenes(existing: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    by_name = {str(item.get("name")): dict(item) for item in existing if item.get("name")}
    for name in _candidate_scenes(text):
        if name not in by_name:
            by_name[name] = _scene_payload(name, len(by_name), context=_near_text(name, text))
    if not by_name:
        by_name["本章主要场景"] = _scene_payload("本章主要场景", 0, context=text[:220])
    return [_normalize_scene(item, index) for index, item in enumerate(by_name.values())]


def _merge_analyzed_scenes(existing: list[dict[str, Any]], analyzed: Any, text: str) -> list[dict[str, Any]]:
    by_name = {str(item.get("name")): dict(item) for item in existing if item.get("name")}
    if isinstance(analyzed, list):
        for item in analyzed:
            if not isinstance(item, dict):
                continue
            name = _clean_entity_name(item.get("name"))
            if not _is_valid_analyzed_scene_name(name):
                continue
            if name in by_name:
                continue
            payload = _scene_payload(name, len(by_name), context=_near_text(name, text))
            for key in ("style_prompt", "lighting", "continuity", "wardrobe_prompt"):
                value = _clean_text(item.get(key), limit=520)
                if value:
                    payload[key] = value
            by_name[name] = payload
    if not by_name:
        return _merge_scenes(existing, text)
    return [_normalize_scene(item, index) for index, item in enumerate(by_name.values())]


def _is_valid_analyzed_scene_name(value: str) -> bool:
    if not value or len(value) < 2 or len(value) > 24:
        return False
    if value in NAME_STOPWORDS or value in SCENE_FALSE_POSITIVES:
        return False
    if re.search(r"(或者|然后|于是|看着|摸索|聚焦|眼神|声音|手里|视野|温柔|冷色月光|暖色烛火)$", value):
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]", value))


def _candidate_scenes(text: str) -> list[str]:
    candidates: list[str] = []
    for pattern in (r"(?:在|来到|回到|进入|走进)([\u4e00-\u9fff]{2,14})", r"([\u4e00-\u9fff]{2,10})(?:中|里|内|外)，"):
        for match in re.finditer(pattern, text):
            name = match.group(1).strip(" ，。！？；、")
            if len(name) >= 2 and name not in NAME_STOPWORDS and name not in candidates:
                candidates.append(name)
    return candidates[:16]


def _scene_payload(name: str, index: int, *, context: str = "") -> dict[str, Any]:
    moods = ("冷色月光", "暖色烛火", "晨雾微光", "雨夜反光", "尘埃逆光", "幽暗高反差")
    mood = moods[index % len(moods)]
    return {
        "id": _safe_id("scene", name),
        "name": name,
        "style_prompt": f"{name}，{mood}，空间结构、材质、色调在后续章节保持一致",
        "lighting": mood,
        "continuity": "same geography, same props placement, same atmosphere and color palette",
        "wardrobe_prompt": _scene_wardrobe_prompt(name, mood, context),
    }


def _normalize_scene(item: dict[str, Any], index: int) -> dict[str, Any]:
    name = str(item.get("name") or f"场景{index + 1}")
    defaults = _scene_payload(name, index)
    merged = {**defaults, **item}
    for key, value in defaults.items():
        if not merged.get(key):
            merged[key] = value
    return merged


def _scene_wardrobe_prompt(name: str, mood: str, context: str) -> str:
    combined = f"{name} {context} {mood}"
    if re.search(r"雨|湿|水|河|江|湖|巷|夜", combined):
        return "雨夜/潮湿场景服装：外层披风或雨披，深色耐脏材质，衣摆和肩部有轻微湿痕，保留角色主识别色与固定识别物"
    if re.search(r"雪|寒|冰|冬|霜", combined):
        return "寒冷场景服装：厚披风、毛边领口或保暖内衬，色彩压低但保留角色主识别色与固定识别物"
    if re.search(r"战|阵|军|营|城墙|兵|血", combined):
        return "战斗场景服装：轻甲、护腕、束紧衣摆和便于行动的靴具，服装有战损但保留角色主识别色与固定识别物"
    if re.search(r"宫|殿|宴|厅|府|堂", combined):
        return "正式室内场景服装：更整洁的外袍或礼服层次，材质更精致，保留角色主识别色、剪裁轮廓和固定识别物"
    if re.search(r"客栈|屋|房|室|楼|阁|铺", combined):
        return "日常室内场景服装：干净常服或轻外袍，行动自然，服装层次适中，保留角色主识别色和固定识别物"
    if re.search(r"山|林|谷|野|路|荒|沙|尘", combined):
        return "野外行进场景服装：便于行动的短披风、护腕、束口裤靴，带少量尘土，保留角色主识别色与固定识别物"
    return "通用场景服装：根据空间温度、身份和行动需求调整外层服饰，保留角色主识别色、剪裁轮廓和固定识别物"


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


def _beats_from_analysis(analysis: dict[str, Any], text: str, count: int) -> list[dict[str, Any] | str]:
    raw_beats = analysis.get("beats")
    plans: list[dict[str, Any]] = []
    if isinstance(raw_beats, list):
        for item in raw_beats:
            if not isinstance(item, dict):
                continue
            summary = _clean_text(item.get("summary"), limit=260)
            if not summary:
                continue
            plans.append(
                {
                    "summary": summary,
                    "scene": _clean_entity_name(item.get("scene")),
                    "speaker": _clean_entity_name(item.get("speaker")),
                    "characters": [_clean_entity_name(name) for name in item.get("characters", [])]
                    if isinstance(item.get("characters"), list)
                    else [],
                    "visual_prompt": _clean_text(item.get("visual_prompt"), limit=620),
                    "camera_motion": _clean_text(item.get("camera_motion"), limit=180),
                    "environment_motion": _clean_text(item.get("environment_motion"), limit=220),
                    "performance": _clean_text(item.get("performance"), limit=220),
                    "lighting": _clean_text(item.get("lighting"), limit=160),
                    "audio_intent": _clean_text(item.get("audio_intent"), limit=220),
                    "wardrobe": _clean_text(item.get("wardrobe"), limit=260),
                }
            )
    fallback = _beats_for_count(text, count)
    if not plans:
        return fallback
    while len(plans) < count:
        index = len(plans)
        plans.append({"summary": fallback[index] if index < len(fallback) else plans[-1]["summary"]})
    if len(plans) > count:
        tail = " ".join(str(item.get("summary") or "") for item in plans[count - 1 :])
        plans = [*plans[: count - 1], {**plans[count - 1], "summary": _truncate(tail, 260)}]
    return plans[:count]


def _shot_payload(
    project: Project,
    *,
    beat: str | dict[str, Any],
    index: int,
    total: int,
    duration: float,
    provider: str,
    characters: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
) -> dict[str, Any]:
    beat_text = _beat_text(beat)
    speaker = _speaker_for_beat_plan(beat, characters)
    scene = _scene_for_beat_plan(beat, scenes)
    visible = _visible_characters_plan(beat, characters, speaker)
    character_lines = [str(item.get("visual_profile") or item.get("name")) for item in visible]
    scene_line = str(scene.get("style_prompt") or scene.get("name"))
    wardrobe_line = _wardrobe_line_for_beat(beat, visible, scene)
    dialogue_cue = "口型与配音台词同步，表情随语气变化" if speaker.get("id") != NARRATOR_ID else "人物动作与旁白节奏同步，场景细节跟随叙事变化"
    visual_prompt = _visual_prompt_for_beat(project, beat, scene_line, character_lines, wardrobe_line, beat_text)
    return {
        "id": f"S{index + 1:03d}",
        "title": f"第{index + 1:03d}镜 · {_truncate(beat_text, 16)}",
        "duration": duration,
        "intent": beat_text,
        "provider": provider,
        "characters": [str(item.get("id")) for item in visible],
        "scene": str(scene.get("id") or ""),
        "speaker": str(speaker.get("id") or NARRATOR_ID),
        "voice": str(speaker.get("voice") or NEUTRAL_VOICES[0]),
        "wardrobe": wardrobe_line,
        "visual_prompt": visual_prompt,
        "camera_motion": _beat_field(beat, "camera_motion") or _camera_for_index(index, total),
        "environment_motion": _beat_field(beat, "environment_motion") or f"{scene.get('name')}内的光影、风、尘埃或道具随旁白节奏轻微运动",
        "performance": _beat_field(beat, "performance") or f"{speaker.get('name')}作为当前声音焦点；{dialogue_cue}",
        "lighting": _beat_field(beat, "lighting") or str(scene.get("lighting") or "cinematic soft light"),
        "audio_intent": _beat_field(beat, "audio_intent")
        or f"说话人={speaker.get('name')}，音色={speaker.get('voice_profile')}，旁白/对白与画面动作同步",
        "subtitle": beat_text,
        "negative_prompt": BASE_NEGATIVE,
        "refs": _refs_for_shot(visible, scene),
    }


def _beat_text(beat: str | dict[str, Any]) -> str:
    if isinstance(beat, dict):
        return _clean_text(beat.get("summary"), limit=260) or "本镜剧情"
    return str(beat)


def _beat_field(beat: str | dict[str, Any], key: str) -> str:
    if not isinstance(beat, dict):
        return ""
    return _clean_text(beat.get(key), limit=420)


def _visual_prompt_for_beat(
    project: Project,
    beat: str | dict[str, Any],
    scene_line: str,
    character_lines: list[str],
    wardrobe_line: str,
    beat_text: str,
) -> str:
    analyzed = _beat_field(beat, "visual_prompt")
    if analyzed:
        return (
            f"原创小说章节镜头，{project.config.aspect_ratio}，{analyzed}。"
            f"场景：{scene_line}。人物：{'；'.join(character_lines)}。"
            f"服装：{wardrobe_line}。剧情：{beat_text}。"
            "电影感叙事画面，角色外形严格一致，服装与场景天气和身份状态对应，动作、口型、表情与配音同步"
        )
    return (
        f"原创小说章节镜头，{project.config.aspect_ratio}，场景：{scene_line}。"
        f"人物：{'；'.join(character_lines)}。服装：{wardrobe_line}。剧情：{beat_text}。"
        "电影感叙事画面，角色外形严格一致，服装必须与当前场景、天气和身份状态对应，场景风格严格一致，动作自然连贯"
    )


def _wardrobe_line_for_beat(beat: str | dict[str, Any], visible: list[dict[str, Any]], scene: dict[str, Any]) -> str:
    base = "；".join(_wardrobe_for_scene(item, scene) for item in visible)
    analyzed = _beat_field(beat, "wardrobe")
    if analyzed and base:
        return f"{analyzed}；穿搭规则：{base}"
    return base or analyzed


def _wardrobe_for_scene(character: dict[str, Any], scene: dict[str, Any]) -> str:
    name = str(character.get("name") or "角色")
    base = str(character.get("wardrobe_profile") or character.get("visual_profile") or name)
    scene_rule = str(scene.get("wardrobe_prompt") or "根据当前场景调整外层服饰")
    scene_name = str(scene.get("name") or "当前场景")
    return f"{name}：{base}；{scene_name}穿搭规则：{scene_rule}"


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


def _speaker_for_beat_plan(beat: str | dict[str, Any], characters: list[dict[str, Any]]) -> dict[str, Any]:
    if isinstance(beat, dict):
        speaker = _match_character(beat.get("speaker"), characters)
        if speaker is not None:
            return speaker
    return _speaker_for_beat(_beat_text(beat), characters)


def _scene_for_beat_plan(beat: str | dict[str, Any], scenes: list[dict[str, Any]]) -> dict[str, Any]:
    if isinstance(beat, dict):
        scene = _match_scene(beat.get("scene"), scenes)
        if scene is not None:
            return scene
    return _scene_for_beat(_beat_text(beat), scenes)


def _visible_characters_plan(beat: str | dict[str, Any], characters: list[dict[str, Any]], speaker: dict[str, Any]) -> list[dict[str, Any]]:
    visible: list[dict[str, Any]] = []
    if isinstance(beat, dict) and isinstance(beat.get("characters"), list):
        for name in beat.get("characters", []):
            character = _match_character(name, characters)
            if character is not None and character.get("id") != NARRATOR_ID and character not in visible:
                visible.append(character)
    if speaker.get("id") != NARRATOR_ID and speaker not in visible:
        visible.insert(0, speaker)
    return visible[:4] or _visible_characters(_beat_text(beat), characters, speaker)


def _match_character(value: Any, characters: list[dict[str, Any]]) -> dict[str, Any] | None:
    name = _clean_entity_name(value)
    if not name:
        return None
    if name in {NARRATOR_ID, NARRATOR_NAME, "narrator"}:
        return next((item for item in characters if item.get("id") == NARRATOR_ID or item.get("name") == NARRATOR_NAME), characters[0])
    for character in characters:
        keys = _character_match_keys(character)
        if name in keys:
            return character
    for character in characters:
        base_name = str(character.get("name") or "")
        if base_name and (base_name in name or name in base_name):
            return character
    return None


def _character_match_keys(character: dict[str, Any]) -> set[str]:
    keys = {_clean_entity_name(character.get("id")), _clean_entity_name(character.get("name"))}
    aliases = character.get("aliases")
    if isinstance(aliases, list):
        keys.update(_clean_entity_name(alias) for alias in aliases)
    return {key for key in keys if key}


def _match_scene(value: Any, scenes: list[dict[str, Any]]) -> dict[str, Any] | None:
    name = _clean_entity_name(value)
    if not name:
        return None
    for scene in scenes:
        keys = {_clean_entity_name(scene.get("id")), _clean_entity_name(scene.get("name"))}
        if name in keys:
            return scene
    for scene in scenes:
        scene_name = str(scene.get("name") or "")
        if scene_name and (scene_name in name or name in scene_name):
            return scene
    return None


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
                    f"wardrobe_profile: {character.get('wardrobe_profile')}",
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
                    f"wardrobe_prompt: {scene.get('wardrobe_prompt')}",
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
