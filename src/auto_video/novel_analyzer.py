from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ANALYZER_OFF = {"", "0", "false", "off", "none", "rule", "rules", "regex", "heuristic"}
ANALYZER_CODEX = {"codex", "llm", "gpt", "gpt-5", "gpt-5.5", "gpt5", "gpt55"}
DEFAULT_ANALYZER_TIMEOUT = 240


@dataclass(frozen=True)
class NovelAnalysis:
    data: dict[str, Any] | None
    source: str
    error: str = ""


ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["characters", "scenes", "beats"],
    "properties": {
        "characters": {
            "type": "array",
            "maxItems": 40,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "gender", "aliases", "visual_profile", "wardrobe_profile", "voice_profile"],
                "properties": {
                    "name": {"type": "string"},
                    "gender": {"type": "string", "enum": ["male", "female", "neutral"]},
                    "aliases": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                    "visual_profile": {"type": "string"},
                    "wardrobe_profile": {"type": "string"},
                    "voice_profile": {"type": "string"},
                },
            },
        },
        "scenes": {
            "type": "array",
            "maxItems": 32,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "style_prompt", "lighting", "continuity", "wardrobe_prompt"],
                "properties": {
                    "name": {"type": "string"},
                    "style_prompt": {"type": "string"},
                    "lighting": {"type": "string"},
                    "continuity": {"type": "string"},
                    "wardrobe_prompt": {"type": "string"},
                },
            },
        },
        "beats": {
            "type": "array",
            "maxItems": 220,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "summary",
                    "scene",
                    "speaker",
                    "characters",
                    "visual_prompt",
                    "camera_motion",
                    "environment_motion",
                    "performance",
                    "lighting",
                    "audio_intent",
                    "wardrobe",
                ],
                "properties": {
                    "summary": {"type": "string"},
                    "scene": {"type": "string"},
                    "speaker": {"type": "string"},
                    "characters": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                    "visual_prompt": {"type": "string"},
                    "camera_motion": {"type": "string"},
                    "environment_motion": {"type": "string"},
                    "performance": {"type": "string"},
                    "lighting": {"type": "string"},
                    "audio_intent": {"type": "string"},
                    "wardrobe": {"type": "string"},
                },
            },
        },
    },
}


def analyze_novel_with_codex(
    *,
    analyzer: str,
    chapter_text: str,
    existing_store: dict[str, Any],
    project_root: Path,
    provider: str,
    shot_count: int,
    target_minutes: float,
) -> NovelAnalysis:
    analyzer_name = (analyzer or os.environ.get("AUTO_VIDEO_NOVEL_ANALYZER") or "").strip().lower()
    if analyzer_name in ANALYZER_OFF:
        return NovelAnalysis(data=None, source="rules")
    if analyzer_name not in ANALYZER_CODEX:
        return NovelAnalysis(data=None, source="rules", error=f"unsupported analyzer {analyzer!r}")

    command_name = os.environ.get("AUTO_VIDEO_NOVEL_ANALYZER_COMMAND", "codex")
    command_path = shutil.which(command_name)
    if not command_path:
        return NovelAnalysis(data=None, source="rules_fallback", error=f"missing command {command_name!r}")

    timeout = _int_env("AUTO_VIDEO_NOVEL_ANALYZER_TIMEOUT", DEFAULT_ANALYZER_TIMEOUT)
    model = os.environ.get("AUTO_VIDEO_NOVEL_ANALYZER_MODEL", "").strip()
    prompt = _analysis_prompt(
        chapter_text=chapter_text,
        existing_store=existing_store,
        provider=provider,
        shot_count=shot_count,
        target_minutes=target_minutes,
    )

    try:
        with tempfile.TemporaryDirectory(prefix="auto-video-novel-") as tmp:
            tmp_path = Path(tmp)
            schema_path = tmp_path / "schema.json"
            output_path = tmp_path / "analysis.json"
            schema_path.write_text(json.dumps(ANALYSIS_SCHEMA, ensure_ascii=False, indent=2), encoding="utf-8")
            command = [
                command_path,
                "exec",
                "--ephemeral",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--ask-for-approval",
                "never",
                "-C",
                project_root.as_posix(),
                "--output-schema",
                schema_path.as_posix(),
                "-o",
                output_path.as_posix(),
            ]
            if model:
                command.extend(["-m", model])
            command.append("-")
            completed = subprocess.run(
                command,
                cwd=project_root,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if completed.returncode != 0:
                return NovelAnalysis(
                    data=None,
                    source="rules_fallback",
                    error=_snippet(completed.stderr or completed.stdout or f"codex exited {completed.returncode}"),
                )
            raw = output_path.read_text(encoding="utf-8") if output_path.exists() else completed.stdout
            data = _parse_json_object(raw)
            if not _has_useful_analysis(data):
                return NovelAnalysis(data=None, source="rules_fallback", error="codex returned empty analysis")
            return NovelAnalysis(data=data, source="codex")
    except subprocess.TimeoutExpired:
        return NovelAnalysis(data=None, source="rules_fallback", error=f"codex timed out after {timeout} seconds")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return NovelAnalysis(data=None, source="rules_fallback", error=_snippet(str(exc)))


def _analysis_prompt(
    *,
    chapter_text: str,
    existing_store: dict[str, Any],
    provider: str,
    shot_count: int,
    target_minutes: float,
) -> str:
    existing_summary = {
        "characters": existing_store.get("characters", [])[:60],
        "scenes": existing_store.get("scenes", [])[:60],
    }
    return f"""
你是“原创小说 AI 视频生产”的资深影视策划、分镜师和提示词工程师。请只输出满足 JSON Schema 的 JSON，不要写 Markdown、解释、注释或代码块。

任务：
1. 从本章小说中抽取真实人物档案、场景档案，并生成 {shot_count} 个按剧情顺序排列的视频分镜 beat。
2. 人物只包含：有姓名的人、明确持续出现且会影响画面/对白的无名角色。不要把代词、连接词、动作短语、身体部位、镜头描述当成人物。
3. 场景只包含：真实空间/地点/房间/街道/设施。不要把“他手里”“视野里缓慢聚焦”“冷色月光”这类身体部位、镜头动作、光线风格当成场景。
4. 如果已有档案里已经存在同名人物或场景，请沿用其身份设定，不要重新发明外形、音色或空间结构。
5. 每个人物需要稳定外形、基础服装、音色描述；不同男女角色的外形和音色必须明显不同。
6. 每个场景需要稳定空间结构、材质、光线、色调、服装适配规则。
7. 每个 beat 的 visual_prompt 要是适合 ComfyUI/Wan 视频生成的关键词式描述：场景、人物、动作、表情、口型/旁白同步、服装适配、镜头、光线都要清楚；避免空泛形容。
8. 每个 beat 的 speaker 如果是对白，填说话人物；如果是旁白或环境叙事，填“旁白”。
9. characters 字段填画面中可见人物名，最多 6 个；不要填“他/她/他们”。

视频目标：
- 目标时长：{target_minutes:g} 分钟
- 分镜数：{shot_count}
- 视频服务：{provider}

已有长期档案：
{json.dumps(existing_summary, ensure_ascii=False, indent=2)}

本章正文：
{chapter_text}
""".strip()


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("analysis JSON must be an object")
    return data


def _has_useful_analysis(data: dict[str, Any]) -> bool:
    return any(isinstance(data.get(key), list) and data.get(key) for key in ("characters", "scenes", "beats"))


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _snippet(value: str, limit: int = 500) -> str:
    stripped = value.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 3] + "..."
