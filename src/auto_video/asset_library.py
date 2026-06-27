from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .models import ASSET_TYPES, REFERENCE_ROLES, REFERENCE_USAGES, Project
from .project import resolve_project_path


LIBRARY_PATH = Path("assets/library.json")
LIBRARY_DIR = Path("assets/refs/library")
MAX_ASSET_BYTES = 20 * 1024 * 1024

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac"}
TEXT_SUFFIXES = {".txt", ".md", ".json"}


def list_asset_library(project: Project) -> list[dict[str, Any]]:
    root = project.config.root
    records = _read_library(root)
    by_path = {str(item.get("path") or ""): _normalize_record(item) for item in records if item.get("path")}
    bindings = _reference_bindings(project)

    refs_dir = root / "assets" / "refs"
    if refs_dir.exists():
        for path in sorted(item for item in refs_dir.rglob("*") if item.is_file()):
            relative = path.relative_to(root).as_posix()
            if relative == LIBRARY_PATH.as_posix():
                continue
            by_path.setdefault(relative, _implicit_record(relative, bindings.get(relative, [])))

    assets = []
    for relative, record in by_path.items():
        bound_refs = bindings.get(relative, [])
        asset_path = resolve_project_path(root, relative)
        payload = {
            **record,
            "id": record.get("id") or _asset_id(relative),
            "path": relative,
            "label": record.get("label") or Path(relative).stem,
            "type": record.get("type") or _infer_type(relative),
            "role": record.get("role") or _first_ref_value(bound_refs, "role", "style_reference"),
            "usage": record.get("usage") or _first_ref_value(bound_refs, "usage", "provide_context"),
            "exists": asset_path.exists(),
            "bytes": asset_path.stat().st_size if asset_path.exists() else record.get("bytes", 0),
            "bound_shots": sorted({str(ref["shot_id"]) for ref in bound_refs}),
        }
        assets.append(payload)
    return sorted(assets, key=lambda item: (str(item.get("label", "")).lower(), str(item.get("path", ""))))


def upload_library_asset(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    label = str(payload.get("label") or payload.get("filename") or "asset").strip()
    asset_type = _require_value(payload.get("type") or _infer_type(str(payload.get("filename") or "")), ASSET_TYPES, "type")
    role = _require_value(payload.get("role") or "style_reference", REFERENCE_ROLES, "role")
    usage = _require_value(payload.get("usage") or "provide_context", REFERENCE_USAGES, "usage")
    filename = str(payload.get("filename") or label).strip()
    body = _asset_body(payload, asset_type)
    if len(body) > MAX_ASSET_BYTES:
        raise ConfigError("素材过大", fix="请上传小于 20 MB 的素材。")

    digest = hashlib.sha1(body).hexdigest()[:12]
    suffix = _safe_suffix(filename, asset_type)
    safe_name = _safe_name(label)
    relative = (LIBRARY_DIR / f"{safe_name}_{digest}{suffix}").as_posix()
    output = resolve_project_path(root, relative)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(body)

    record = {
        "id": f"asset_{digest}",
        "label": label,
        "path": relative,
        "type": asset_type,
        "role": role,
        "usage": usage,
        "bytes": len(body),
        "created_at": datetime.now(UTC).isoformat(),
    }
    records = [item for item in _read_library(root) if item.get("id") != record["id"] and item.get("path") != relative]
    records.append(record)
    _write_library(root, records)
    return record


def delete_library_asset(project: Project, asset_id: str) -> dict[str, Any]:
    root = project.config.root
    assets = list_asset_library(project)
    asset = next((item for item in assets if item.get("id") == asset_id), None)
    if asset is None:
        raise ConfigError("素材不存在", fix="请刷新素材库后重试。")
    relative = str(asset.get("path") or "")
    if not relative:
        raise ConfigError("素材路径缺失", fix="请刷新素材库后重试。")

    records = [item for item in _read_library(root) if item.get("id") != asset_id and item.get("path") != relative]
    _write_library(root, records)
    path = resolve_project_path(root, relative)
    if path.exists() and path.is_file():
        path.unlink()
    return {"deleted": asset_id, "path": relative}


def _read_library(root: Path) -> list[dict[str, Any]]:
    path = root / LIBRARY_PATH
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_assets = data.get("assets") if isinstance(data, dict) else None
    if raw_assets is None:
        raw_assets = data if isinstance(data, list) else []
    if not isinstance(raw_assets, list):
        raise ConfigError("assets/library.json 格式错误", fix="请使用包含 assets 数组的 JSON 文件。")
    return [dict(item) for item in raw_assets if isinstance(item, dict)]


def _write_library(root: Path, records: list[dict[str, Any]]) -> None:
    path = root / LIBRARY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"assets": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _normalize_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or ""),
        "label": str(item.get("label") or ""),
        "path": str(item.get("path") or ""),
        "type": str(item.get("type") or ""),
        "role": str(item.get("role") or ""),
        "usage": str(item.get("usage") or ""),
        "bytes": int(item.get("bytes") or 0),
        "created_at": str(item.get("created_at") or ""),
    }


def _implicit_record(relative: str, refs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": _asset_id(relative),
        "label": Path(relative).stem,
        "path": relative,
        "type": _infer_type(relative),
        "role": _first_ref_value(refs, "role", "style_reference"),
        "usage": _first_ref_value(refs, "usage", "provide_context"),
    }


def _reference_bindings(project: Project) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for shot in project.shots:
        for ref in shot.refs:
            result.setdefault(ref.path, []).append(
                {
                    "shot_id": shot.id,
                    "type": ref.type,
                    "role": ref.role,
                    "usage": ref.usage,
                }
            )
    return result


def _first_ref_value(refs: list[dict[str, Any]], key: str, default: str) -> str:
    for ref in refs:
        value = str(ref.get(key) or "")
        if value:
            return value
    return default


def _asset_body(payload: dict[str, Any], asset_type: str) -> bytes:
    if asset_type == "text" and payload.get("text") is not None:
        return str(payload.get("text") or "").encode("utf-8")
    data_url = str(payload.get("data_url") or "")
    encoded = data_url.split(",", 1)[1] if "," in data_url else str(payload.get("data_base64") or "")
    if not encoded:
        raise ConfigError("素材内容为空", fix="请选择文件或输入文本内容。")
    return base64.b64decode(encoded, validate=True)


def _require_value(value: Any, allowed: set[str], field_name: str) -> str:
    text = str(value or "").strip()
    if text not in allowed:
        raise ConfigError(f"{field_name} 不支持：{text}", fix=f"请使用：{', '.join(sorted(allowed))}。")
    return text


def _asset_id(relative: str) -> str:
    return "asset_" + hashlib.sha1(relative.encode("utf-8")).hexdigest()[:12]


def _safe_suffix(filename: str, asset_type: str) -> str:
    suffix = Path(filename).suffix.lower()
    allowed = {
        "image": IMAGE_SUFFIXES,
        "video": VIDEO_SUFFIXES,
        "audio": AUDIO_SUFFIXES,
        "text": TEXT_SUFFIXES,
    }.get(asset_type, set())
    if suffix in allowed:
        return suffix
    return {"image": ".png", "video": ".mp4", "audio": ".wav", "text": ".txt"}.get(asset_type, ".bin")


def _infer_type(value: str) -> str:
    suffix = Path(value).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    if suffix in TEXT_SUFFIXES:
        return "text"
    return "image"


def _safe_name(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value).strip("_")
    return safe or "asset"
