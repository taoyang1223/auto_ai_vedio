from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import shlex
import shutil
import subprocess
import time
from argparse import Namespace
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import yaml

from .asset_library import delete_library_asset, list_asset_library, upload_library_asset
from .continuity import extract_tail_frames
from .errors import AutoVideoError, ConfigError
from .comfyui_runtime_doctor import run as run_comfyui_doctor
from .first_frame_generation import generate_first_frames, promote_generated_images_to_first_frames
from .first_frame_prompt import draft_first_frame_prompts, save_first_frame_prompts
from .models import AssetRef, PromptProfile
from .novel import apply_novel_chapter, draft_novel_chapter, load_novel_store
from .pipeline import plan_jobs, submit_jobs
from .probe import probe_project
from .project import load_project, resolve_project_path
from .remote_profiles import build_remote_run_options_from_profile
from .remote_transport import run_remote_worker
from .remote_wrapup import RemoteWrapupOptions, run_remote_wrapup
from .render import assemble_project
from .script_storyboard import draft_storyboard_from_script
from .shot_policy import shot_needs_lipsync
from .templates import init_project, list_templates
from .validation import validate_project
from .web_tasks import TaskLogger, WebTaskQueue
from .workflow_registry import (
    comfyui_image_adapter_options,
    comfyui_lipsync_adapter_options,
    comfyui_wan_adapter_options,
    list_workflows,
)


PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_WORKFLOW_JSON_BYTES = 5 * 1024 * 1024
STATIC_DIR = Path(__file__).with_name("web_static")
SESSION_COOKIE = "auto_video_web_session"
DEFAULT_TOKEN_ENV = "AUTO_VIDEO_WEB_TOKEN"
ACTION_LABELS = {
    "validate": "校验项目",
    "jobs-plan": "生成计划",
    "generate": "提交生成",
    "lipsync-plan": "口型同步预案",
    "lipsync": "口型同步",
    "first-frame-generate": "生成首帧",
    "probe": "验片",
    "assemble-plan": "合成预案",
    "assemble": "合成成片",
    "comfyui-check": "检查 ComfyUI 连接",
    "remote-plan": "远程预案",
    "remote-run": "远程执行",
    "remote-first-frame": "远程生成首帧",
    "produce-all": "一键完整生产",
    "continuity": "提取连续性尾帧",
    "remote-wrapup": "远程收尾检查",
    "novel-draft": "生成小说章节草稿",
}
PROMPT_PROFILE_KEYS = tuple(PromptProfile.__dataclass_fields__)
PRODUCTION_PIPELINE = [
    {"key": "validate", "label": "项目校验", "tab": "run"},
    {"key": "first_frames", "label": "首帧素材", "tab": "first_frames"},
    {"key": "videos", "label": "分镜视频", "tab": "review"},
    {"key": "voiceover", "label": "分镜配音", "tab": "voice"},
    {"key": "lipsync", "label": "口型同步", "tab": "run"},
    {"key": "probe", "label": "自动验片", "tab": "review"},
    {"key": "assemble", "label": "最终成片", "tab": "review"},
]
PRODUCTION_STEP_BY_LOG_INDEX = {
    1: "validate",
    2: "first_frames",
    3: "videos",
    4: "voiceover",
    5: "lipsync",
    6: "probe",
    7: "assemble",
}
REMOTE_PROGRESS_CACHE_TTL_SECONDS = 10.0
REMOTE_PREVIEW_SYNC_CACHE_TTL_SECONDS = 30.0
_REMOTE_PROGRESS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_REMOTE_PREVIEW_SYNC_CACHE: dict[str, float] = {}


def run_web_server(
    workspace: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str | None = None,
    token_env: str = DEFAULT_TOKEN_ENV,
) -> None:
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    auth_token = token or os.environ.get(token_env)
    server = make_web_server(workspace, host=host, port=port, token=auth_token)
    print(f"auto-video web listening on http://{host}:{server.server_port}")
    print(f"auto-video web auth {'enabled' if auth_token else 'disabled'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def make_web_server(
    workspace: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    token: str | None = None,
) -> ThreadingHTTPServer:
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    handler = _handler_factory(workspace, token=token)
    return ThreadingHTTPServer((host, port), handler)


def _handler_factory(workspace: Path, *, token: str | None):
    session_value = _session_value(token) if token else None
    task_queue = WebTaskQueue()

    class AutoVideoWebHandler(BaseHTTPRequestHandler):
        server_version = "AutoVideoWeb/0.1"

        def do_GET(self) -> None:
            self._handle("GET")

        def do_POST(self) -> None:
            self._handle("POST")

        def do_PUT(self) -> None:
            self._handle("PUT")

        def do_DELETE(self) -> None:
            self._handle("DELETE")

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _handle(self, method: str) -> None:
            try:
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/") or "/"
                parts = [unquote(part) for part in path.split("/") if part]
                if parts[:1] == ["api"]:
                    if parts[1:2] == ["auth"]:
                        self._handle_auth(method, parts[2:])
                        return
                    if not self._is_authorized():
                        self._send_unauthorized()
                        return
                    self._handle_api(method, parts[1:])
                    return
                if method == "GET" and parts[:1] == ["media"]:
                    if not self._is_authorized():
                        self._send_unauthorized()
                        return
                    self._handle_media(parts[1:])
                    return
                if method == "GET" and path == "/":
                    if self._send_static("index.html"):
                        return
                    self._send_html(APP_HTML)
                    return
                if method == "GET" and path == "/app.css":
                    self._send_text(APP_CSS, "text/css; charset=utf-8")
                    return
                if method == "GET" and path == "/app.js":
                    self._send_text(APP_JS, "application/javascript; charset=utf-8")
                    return
                if method == "GET" and self._send_static(path.lstrip("/") or "index.html"):
                    return
                if method == "GET" and self._send_static("index.html"):
                    return
                raise ConfigError("unknown route", fix="Use the web console API routes.")
            except AutoVideoError as exc:
                self._send_json({"ok": False, "error": exc.message, "fix": exc.fix}, status=400)
            except json.JSONDecodeError as exc:
                self._send_json({"ok": False, "error": "invalid JSON", "fix": str(exc)}, status=400)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc), "fix": "Check the request and server log."}, status=500)

        def _handle_auth(self, method: str, parts: list[str]) -> None:
            if method == "GET" and parts == ["status"]:
                self._send_json(
                    {
                        "ok": True,
                        "enabled": bool(token),
                        "authenticated": self._is_authorized(),
                    }
                )
                return
            if method == "POST" and parts == ["login"]:
                if not token:
                    self._send_json({"ok": True, "enabled": False, "authenticated": True})
                    return
                payload = self._read_json()
                candidate = str(payload.get("token") or "")
                if hmac.compare_digest(candidate, token):
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header(
                        "Set-Cookie",
                        f"{SESSION_COOKIE}={session_value}; Path=/; HttpOnly; SameSite=Lax",
                    )
                    body = json.dumps({"ok": True, "enabled": True, "authenticated": True}).encode("utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self._send_json(
                    {"ok": False, "error": "访问口令不正确", "fix": "请检查口令后重试。"},
                    status=401,
                )
                return
            if method == "POST" and parts == ["logout"]:
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header(
                    "Set-Cookie",
                    f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
                )
                body = json.dumps({"ok": True, "authenticated": False}).encode("utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            raise ConfigError("unknown auth API route", fix="Use /api/auth/login or /api/auth/status.")

        def _handle_api(self, method: str, parts: list[str]) -> None:
            if parts[:1] == ["tasks"]:
                self._handle_tasks(method, parts[1:])
                return
            if method == "GET" and parts == ["templates"]:
                self._send_json({"ok": True, "templates": list_templates()})
                return
            if method == "GET" and parts == ["projects"]:
                self._send_json({"ok": True, "workspace": workspace.as_posix(), "projects": _list_projects(workspace)})
                return
            if method == "POST" and parts == ["projects"]:
                payload = self._read_json()
                name = str(payload.get("name") or "").strip()
                template = str(payload.get("template") or "autodl_comfyui_wan")
                project_root = _project_path(workspace, name)
                init_project(project_root, template_name=template, force=bool(payload.get("force", False)))
                self._send_json({"ok": True, "project": _project_summary(project_root)})
                return
            if len(parts) < 2 or parts[0] != "projects":
                raise ConfigError("unknown API route", fix="Use /api/projects.")

            project_name = parts[1]
            project_root = _project_path(workspace, project_name)
            tail = parts[2:]
            if method == "DELETE" and not tail:
                _delete_project(project_root, task_queue.list(project=project_name))
                self._send_json({"ok": True, "deleted": project_name})
                return
            _ensure_project_exists(project_root)
            if method == "GET" and not tail:
                self._send_json({"ok": True, "project": _project_detail(project_root)})
                return
            if method == "GET" and tail == ["config"]:
                self._send_json({"ok": True, "text": (project_root / "project.yaml").read_text(encoding="utf-8")})
                return
            if method == "PUT" and tail == ["config"]:
                text = str(self._read_json().get("text", ""))
                _write_project_config(project_root, text)
                self._send_json({"ok": True, "project": _project_detail(project_root)})
                return
            if method == "PUT" and tail == ["shots"]:
                payload = self._read_json()
                _write_shots(project_root, payload.get("shots"))
                self._send_json({"ok": True, "project": _project_detail(project_root)})
                return
            if method == "GET" and tail == ["assets"]:
                self._send_json({"ok": True, "assets": list_asset_library(load_project(project_root))})
                return
            if method == "POST" and tail == ["assets"]:
                asset = upload_library_asset(project_root, self._read_json())
                self._send_json({"ok": True, "asset": asset, "assets": list_asset_library(load_project(project_root))})
                return
            if method == "DELETE" and len(tail) == 2 and tail[0] == "assets":
                result = delete_library_asset(load_project(project_root), tail[1])
                _remove_asset_refs(project_root, str(result.get("path") or ""))
                self._send_json({"ok": True, **result, "assets": list_asset_library(load_project(project_root)), "project": _project_detail(project_root)})
                return
            if method == "PUT" and tail == ["shot-refs"]:
                result = _update_shot_refs(project_root, self._read_json())
                self._send_json({"ok": True, **result, "assets": list_asset_library(load_project(project_root)), "project": _project_detail(project_root)})
                return
            if method == "GET" and tail == ["first-frame-prompts"]:
                self._send_json({"ok": True, "prompts": draft_first_frame_prompts(load_project(project_root))})
                return
            if method == "PUT" and tail == ["first-frame-prompts"]:
                prompts = save_first_frame_prompts(load_project(project_root), self._read_json())
                self._send_json({"ok": True, "prompts": prompts})
                return
            if method == "PUT" and tail == ["prompt-profile"]:
                result = _update_prompt_profile(project_root, self._read_json())
                self._send_json({"ok": True, **result, "project": _project_detail(project_root)})
                return
            if method == "POST" and tail == ["script-draft"]:
                result = draft_storyboard_from_script(load_project(project_root), self._read_json())
                self._send_json({"ok": True, **result})
                return
            if method == "POST" and tail == ["script-apply"]:
                result = _apply_script_storyboard(project_root, self._read_json())
                self._send_json({"ok": True, **result, "project": _project_detail(project_root)})
                return
            if method == "GET" and tail == ["novel"]:
                self._send_json({"ok": True, "novel": load_novel_store(project_root)})
                return
            if method == "POST" and tail == ["novel-draft"]:
                result = draft_novel_chapter(load_project(project_root), self._read_json())
                self._send_json({"ok": True, **result})
                return
            if method == "POST" and tail == ["novel-apply"]:
                result = apply_novel_chapter(project_root, self._read_json())
                self._send_json({"ok": True, **result, "project": _project_detail(project_root), "novel": load_novel_store(project_root)})
                return
            if method == "POST" and tail == ["first-frame"]:
                result = _upload_first_frame(project_root, self._read_json())
                self._send_json({"ok": True, **result, "project": _project_detail(project_root)})
                return
            if method == "GET" and tail == ["tasks"]:
                tasks = [_task_with_progress(workspace, task) for task in task_queue.list(project=project_name)]
                self._send_json({"ok": True, "tasks": tasks})
                return
            if method == "POST" and tail == ["tasks"]:
                task = _enqueue_project_task(task_queue, project_name, project_root, self._read_json())
                self._send_json({"ok": True, "task": _task_with_progress(workspace, task)}, status=202)
                return
            if method == "POST" and tail == ["workflow-check"]:
                result = _run_project_action(project_root, "comfyui-check", self._read_json())
                self._send_json({"ok": True, "result": result})
                return
            if method == "PUT" and len(tail) == 2 and tail[0] == "workflows":
                result = _update_workflow_settings(project_root, tail[1], self._read_json())
                self._send_json({"ok": True, **result, "project": _project_detail(project_root)})
                return
            if method == "PUT" and len(tail) == 2 and tail[0] == "remote-profiles":
                result = _update_remote_profile(project_root, tail[1], self._read_json())
                self._send_json({"ok": True, **result, "project": _project_detail(project_root)})
                return
            if method == "POST" and tail == ["validate"]:
                result = _run_project_action(project_root, "validate", self._read_json())
                self._send_json({"ok": True, **result})
                return
            if method == "POST" and tail == ["jobs-plan"]:
                result = _run_project_action(project_root, "jobs-plan", self._read_json())
                self._send_json({"ok": True, "result": result})
                return
            if method == "POST" and tail == ["probe"]:
                result = _run_project_action(project_root, "probe", self._read_json())
                self._send_json({"ok": True, "result": result})
                return
            if method == "POST" and tail == ["assemble-plan"]:
                result = _run_project_action(project_root, "assemble-plan", self._read_json())
                self._send_json({"ok": True, "result": result})
                return
            if method == "POST" and tail == ["remote-plan"]:
                result = _run_project_action(project_root, "remote-plan", self._read_json())
                self._send_json({"ok": True, "result": result})
                return
            raise ConfigError("unknown project API route", fix="Refresh the web console and retry.")

        def _handle_tasks(self, method: str, parts: list[str]) -> None:
            if method == "GET" and not parts:
                tasks = [_task_with_progress(workspace, task) for task in task_queue.list()]
                self._send_json({"ok": True, "tasks": tasks})
                return
            if method == "GET" and len(parts) == 1:
                task = task_queue.get(parts[0])
                if task is None:
                    raise ConfigError("task not found", fix="Refresh the task list.")
                self._send_json({"ok": True, "task": _task_with_progress(workspace, task)})
                return
            if method == "POST" and len(parts) == 2 and parts[1] == "cancel":
                task = task_queue.cancel(parts[0])
                if task is None:
                    raise ConfigError("task not found", fix="Refresh the task list.")
                self._send_json({"ok": True, "task": _task_with_progress(workspace, task)})
                return
            raise ConfigError("unknown task API route", fix="Use /api/tasks or /api/tasks/<id>.")

        def _handle_media(self, parts: list[str]) -> None:
            if len(parts) < 2:
                raise ConfigError("invalid media route", fix="Use /media/<project>/<relative-path>.")
            project_root = _project_path(workspace, parts[0])
            relative = "/".join(parts[1:])
            media_path = resolve_project_path(project_root, relative)
            if not media_path.exists() or not media_path.is_file():
                raise ConfigError("media file not found", fix="Upload or regenerate the referenced asset.")
            self._send_file(media_path)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def _send_html(self, body: str, status: int = 200) -> None:
            self._send_text(body, "text/html; charset=utf-8", status=status)

        def _send_text(self, body: str, content_type: str, status: int = 200) -> None:
            raw = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _send_unauthorized(self) -> None:
            self._send_json(
                {"ok": False, "error": "未登录", "fix": "请先输入访问口令。"},
                status=401,
            )

        def _is_authorized(self) -> bool:
            if not token or not session_value:
                return True
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer ") and hmac.compare_digest(auth.removeprefix("Bearer "), token):
                return True
            cookies = _parse_cookie_header(self.headers.get("Cookie", ""))
            return hmac.compare_digest(cookies.get(SESSION_COOKIE, ""), session_value)

        def _send_static(self, relative_path: str) -> bool:
            if not STATIC_DIR.exists():
                return False
            candidate = (STATIC_DIR / relative_path).resolve()
            static_root = STATIC_DIR.resolve()
            if candidate != static_root and static_root not in candidate.parents:
                return False
            if not candidate.exists() or not candidate.is_file():
                return False
            self._send_file(candidate)
            return True

        def _send_file(self, path: Path) -> None:
            body = path.read_bytes()
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return AutoVideoWebHandler


def _session_value(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _parse_cookie_header(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in value.split(";"):
        if "=" not in item:
            continue
        name, raw = item.split("=", 1)
        result[name.strip()] = raw.strip()
    return result


def _list_projects(workspace: Path) -> list[dict[str, Any]]:
    projects = []
    for child in sorted(workspace.iterdir(), key=lambda item: item.name.lower()):
        if child.is_dir() and (child / "project.yaml").exists() and (child / "shots.json").exists():
            projects.append(_project_summary(child))
    return projects


def _project_summary(root: Path) -> dict[str, Any]:
    try:
        project = load_project(root)
        return {
            "name": root.name,
            "title": project.config.name,
            "path": root.as_posix(),
            "shots": len(project.shots),
            "provider": project.config.default_video_provider,
            "workflows": len(project.config.comfyui_workflows),
            "remote_profiles": len(project.config.remote_profiles),
        }
    except AutoVideoError as exc:
        return {"name": root.name, "path": root.as_posix(), "error": exc.message, "fix": exc.fix}


def _project_detail(root: Path) -> dict[str, Any]:
    project = load_project(root)
    manifest_shots = project.manifest.get("shots", {})
    video_refresh_ids = _video_refresh_ids(project)
    audio_refresh_ids = _audio_refresh_ids(project)
    lipsync_refresh_ids = _lipsync_refresh_ids(project)
    shots = []
    for shot in project.shots:
        shot_payload = asdict(shot)
        shot_manifest = manifest_shots.get(shot.id, {})
        shot_payload["manifest"] = shot_manifest
        shot_payload["freshness"] = _shot_freshness(shot.id, shot_manifest, video_refresh_ids)
        shot_payload["voice_freshness"] = _audio_freshness(shot.id, shot_manifest, audio_refresh_ids)
        shot_payload["lipsync_freshness"] = _lipsync_freshness(shot.id, shot_manifest, lipsync_refresh_ids)
        shots.append(shot_payload)
    return {
        **_project_summary(root),
        "config": {
            "aspect_ratio": project.config.aspect_ratio,
            "width": project.config.width,
            "height": project.config.height,
            "fps": project.config.fps,
            "default_video_provider": project.config.default_video_provider,
            "default_image_provider": project.config.default_image_provider,
            "default_audio_provider": project.config.default_audio_provider,
            "default_lipsync_provider": project.config.default_lipsync_provider,
        },
        "prompt_profile": asdict(project.config.prompt_profile),
        "shots_detail": shots,
        "remote_profiles_detail": _remote_profiles_detail(project),
        "workflows_detail": list_workflows(project),
        "renders": project.manifest.get("renders", {}),
    }


def _task_with_progress(workspace: Path, task: dict[str, Any]) -> dict[str, Any]:
    result = dict(task)
    project_name = str(result.get("project") or "")
    if not PROJECT_NAME_RE.match(project_name):
        return result
    project_root = _project_path(workspace, project_name)
    if not (project_root / "project.yaml").exists():
        return result
    try:
        result["progress"] = _task_progress(project_root, result)
    except AutoVideoError as exc:
        result["progress"] = {"available": False, "error": exc.message, "fix": exc.fix}
    except Exception as exc:
        result["progress"] = {"available": False, "error": str(exc)}
    return result


def _task_progress(project_root: Path, task: dict[str, Any]) -> dict[str, Any]:
    action = str(task.get("action") or "")
    if action == "produce-all":
        return _production_task_progress(project_root, task)
    if action in {"generate", "remote-run"}:
        return _single_generation_progress(project_root, task)
    if action in {"first-frame-generate", "remote-first-frame"}:
        return _single_generation_progress(project_root, task, forced_step="first_frames")
    if action == "lipsync":
        return _single_generation_progress(project_root, task, forced_step="lipsync")
    return {"available": False}


def _production_task_progress(project_root: Path, task: dict[str, Any]) -> dict[str, Any]:
    project = load_project(project_root)
    shot_ids_by_step = _progress_shot_ids(project)
    shot_ids = shot_ids_by_step["videos"]
    totals = _progress_totals(shot_ids_by_step)
    remote_media = _remote_progress_media(project, task)
    local_media = _local_progress_media(project)
    counts = {
        "first_frames": max(_first_frame_count(project), len(remote_media.get("first_frames", []))),
        "videos": max(len(local_media["videos"]), len(remote_media.get("videos", []))),
        "voiceover": len(local_media["audio"]),
        "lipsync": max(len(local_media["lipsync"]), len(remote_media.get("lipsync", []))),
        "assemble": len(local_media["final"]),
    }
    active_key = _active_pipeline_key(task, counts, totals)
    steps = _pipeline_steps(task, active_key, counts, totals)
    media = [*local_media["videos"], *local_media["lipsync"], *local_media["final"]]
    current = _current_item(active_key, shot_ids_by_step.get(active_key or "", shot_ids), counts)
    return {
        "available": True,
        "kind": "production",
        "status": task.get("status"),
        "current_module": active_key,
        "current_label": _pipeline_label(active_key),
        "current_item": current,
        "percent": _overall_percent(steps, task),
        "steps": steps,
        "media": media,
        "remote": {
            "profile": _progress_profile_name(project, task),
            "videos_done": len(remote_media.get("videos", [])),
            "first_frames_done": len(remote_media.get("first_frames", [])),
            "lipsync_done": len(remote_media.get("lipsync", [])),
        },
        "pause": _pause_state(task),
    }


def _single_generation_progress(project_root: Path, task: dict[str, Any], *, forced_step: str | None = None) -> dict[str, Any]:
    project = load_project(project_root)
    shot_ids_by_step = _progress_shot_ids(project)
    remote_media = _remote_progress_media(project, task)
    local_media = _local_progress_media(project)
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    kind = str(payload.get("kind") or "")
    active_key = forced_step or ("lipsync" if kind == "lipsync" else "first_frames" if kind == "image" else "videos")
    active_shot_ids = shot_ids_by_step.get(active_key, shot_ids_by_step["videos"])
    total = len(active_shot_ids)
    counts = {
        "first_frames": max(_first_frame_count(project), len(remote_media.get("first_frames", []))),
        "videos": max(len(local_media["videos"]), len(remote_media.get("videos", []))),
        "voiceover": len(local_media["audio"]),
        "lipsync": max(len(local_media["lipsync"]), len(remote_media.get("lipsync", []))),
        "assemble": len(local_media["final"]),
    }
    steps = [
        _step_payload(
            active_key,
            _pipeline_label(active_key),
            counts.get(active_key, 0),
            total if active_key != "assemble" else 1,
            status="running" if task.get("status") == "running" else "done" if task.get("status") == "succeeded" else str(task.get("status") or "pending"),
        )
    ]
    return {
        "available": True,
        "kind": "module",
        "status": task.get("status"),
        "current_module": active_key,
        "current_label": _pipeline_label(active_key),
        "current_item": _current_item(active_key, active_shot_ids, counts),
        "percent": _overall_percent(steps, task),
        "steps": steps,
        "media": [*local_media["videos"], *local_media["lipsync"], *local_media["final"]],
        "remote": {
            "profile": _progress_profile_name(project, task),
            "videos_done": len(remote_media.get("videos", [])),
            "first_frames_done": len(remote_media.get("first_frames", [])),
            "lipsync_done": len(remote_media.get("lipsync", [])),
        },
        "pause": _pause_state(task),
    }


def _pipeline_steps(task: dict[str, Any], active_key: str | None, counts: dict[str, int], totals: dict[str, int]) -> list[dict[str, Any]]:
    active_index = _pipeline_index(active_key)
    steps: list[dict[str, Any]] = []
    for index, raw in enumerate(PRODUCTION_PIPELINE):
        key = str(raw["key"])
        total = totals.get(key, 1)
        completed = 0
        if key == "validate":
            completed = 1 if task.get("status") in {"running", "succeeded", "failed"} else 0
        elif key == "probe":
            completed = 1 if _pipeline_index("assemble") <= active_index or task.get("status") == "succeeded" else 0
        elif key == "assemble":
            completed = min(counts.get("assemble", 0), 1)
        else:
            completed = min(counts.get(key, 0), total)
        if task.get("status") == "succeeded":
            status = "done"
        elif task.get("status") == "failed" and key == active_key:
            status = "failed"
        elif active_key == key and task.get("status") == "running":
            status = "running"
        elif index < active_index:
            status = "done"
            completed = total
        elif completed >= total and total > 0:
            status = "done"
        else:
            status = "pending"
        steps.append(_step_payload(key, str(raw["label"]), completed, total, status=status, tab=str(raw["tab"])))
    return steps


def _step_payload(
    key: str,
    label: str,
    completed: int,
    total: int,
    *,
    status: str,
    tab: str | None = None,
) -> dict[str, Any]:
    safe_total = max(total, 1)
    percent = int(round((min(completed, safe_total) / safe_total) * 100))
    return {
        "key": key,
        "label": label,
        "completed": completed,
        "total": total,
        "percent": percent,
        "status": status,
        "tab": tab,
    }


def _overall_percent(steps: list[dict[str, Any]], task: dict[str, Any]) -> int:
    if not steps:
        return 0
    if task.get("status") == "succeeded":
        return 100
    done = sum(float(step.get("percent") or 0) / 100 for step in steps)
    return int(round((done / len(steps)) * 100))


def _active_pipeline_key(task: dict[str, Any], counts: dict[str, int], totals: dict[str, int]) -> str | None:
    status = str(task.get("status") or "")
    logs = task.get("logs") if isinstance(task.get("logs"), list) else []
    for raw in reversed(logs):
        message = str(raw.get("message") if isinstance(raw, dict) else raw)
        match = re.search(r"步骤\s*(\d+)\s*/\s*7", message)
        if match:
            return PRODUCTION_STEP_BY_LOG_INDEX.get(int(match.group(1)))
    if status in {"queued"}:
        return "validate"
    if status in {"succeeded"}:
        return "assemble"
    for key in ("first_frames", "videos", "voiceover", "lipsync"):
        if counts.get(key, 0) < totals.get(key, 0):
            return key
    if counts.get("assemble", 0) <= 0:
        return "assemble"
    return None


def _pipeline_label(key: str | None) -> str:
    for step in PRODUCTION_PIPELINE:
        if step["key"] == key:
            return str(step["label"])
    return "等待调度"


def _pipeline_index(key: str | None) -> int:
    for index, step in enumerate(PRODUCTION_PIPELINE):
        if step["key"] == key:
            return index
    return 0


def _current_item(active_key: str | None, shot_ids: list[str], counts: dict[str, int]) -> dict[str, Any] | None:
    if active_key not in {"first_frames", "videos", "voiceover", "lipsync"} or not shot_ids:
        return None
    completed = min(max(counts.get(active_key, 0), 0), len(shot_ids))
    index = min(completed, len(shot_ids) - 1)
    return {"shot_id": shot_ids[index], "index": index + 1, "total": len(shot_ids)}


def _progress_shot_ids(project: Any) -> dict[str, list[str]]:
    all_ids = [shot.id for shot in project.shots]
    lipsync_ids = [shot.id for shot in project.shots if shot_needs_lipsync(shot)]
    return {
        "first_frames": all_ids,
        "videos": all_ids,
        "voiceover": all_ids,
        "lipsync": lipsync_ids,
    }


def _progress_totals(shot_ids_by_step: dict[str, list[str]]) -> dict[str, int]:
    return {
        "validate": 1,
        "first_frames": len(shot_ids_by_step.get("first_frames", [])),
        "videos": len(shot_ids_by_step.get("videos", [])),
        "voiceover": len(shot_ids_by_step.get("voiceover", [])),
        "lipsync": len(shot_ids_by_step.get("lipsync", [])),
        "probe": 1,
        "assemble": 1,
    }


def _pause_state(task: dict[str, Any]) -> dict[str, Any]:
    status = str(task.get("status") or "")
    requested = bool(task.get("cancel_requested", False))
    return {
        "requested": requested,
        "available": status in {"queued", "running"},
        "mode": "instant" if status == "queued" else "soft" if status == "running" else "none",
        "label": "暂停请求中" if requested else "可暂停" if status in {"queued", "running"} else "不可暂停",
    }


def _local_progress_media(project: Any) -> dict[str, list[dict[str, Any]]]:
    videos: list[dict[str, Any]] = []
    audio: list[dict[str, Any]] = []
    lipsync: list[dict[str, Any]] = []
    for shot in project.shots:
        clip = _shot_media_path(project, shot.id, "clip", [f"generated/clips/{shot.id}.mp4"])
        if clip:
            videos.append(_media_item(project, "video", clip, shot_id=shot.id, title=shot.title or shot.id))
        voice = _shot_media_path(project, shot.id, "audio", [f"generated/audio/{shot.id}.wav", f"generated/audio/{shot.id}.mp3"])
        if voice:
            audio.append(_media_item(project, "audio", voice, shot_id=shot.id, title=shot.title or shot.id))
        synced = _shot_media_path(project, shot.id, "lipsync_clip", [f"generated/lipsync/{shot.id}.mp4"])
        if synced:
            lipsync.append(_media_item(project, "lipsync", synced, shot_id=shot.id, title=shot.title or shot.id))
    final: list[dict[str, Any]] = []
    renders = project.manifest.get("renders", {}) if isinstance(project.manifest, dict) else {}
    if isinstance(renders, dict):
        for name, raw in sorted(renders.items()):
            if not isinstance(raw, dict):
                continue
            path = _existing_relative_path(project.config.root, str(raw.get("path") or ""))
            if path:
                final.append(_media_item(project, "final", path, shot_id=None, title=str(name)))
    return {"videos": videos, "audio": audio, "lipsync": lipsync, "final": final}


def _first_frame_count(project: Any) -> int:
    count = 0
    for shot in project.shots:
        linked = next((ref.path for ref in shot.refs if ref.role == "first_frame"), "")
        if _existing_relative_path(project.config.root, linked) or _existing_relative_path(project.config.root, f"generated/images/{shot.id}.png"):
            count += 1
    return count


def _shot_media_path(project: Any, shot_id: str, manifest_key: str, fallbacks: list[str]) -> str | None:
    manifest_shots = project.manifest.get("shots", {}) if isinstance(project.manifest, dict) else {}
    shot_manifest = manifest_shots.get(shot_id, {}) if isinstance(manifest_shots, dict) else {}
    if isinstance(shot_manifest, dict):
        manifest_path = _existing_relative_path(project.config.root, str(shot_manifest.get(manifest_key) or ""))
        if manifest_path:
            return manifest_path
    for fallback in fallbacks:
        existing = _existing_relative_path(project.config.root, fallback)
        if existing:
            return existing
    return None


def _existing_relative_path(root: Path, value: str) -> str | None:
    if not value:
        return None
    try:
        path = resolve_project_path(root, value)
    except AutoVideoError:
        return None
    return value if path.exists() and path.is_file() else None


def _media_item(project: Any, kind: str, relative: str, *, shot_id: str | None, title: str) -> dict[str, Any]:
    path = resolve_project_path(project.config.root, relative)
    stat = path.stat()
    return {
        "kind": kind,
        "shot_id": shot_id,
        "title": title,
        "path": relative,
        "bytes": stat.st_size,
        "updated_at": stat.st_mtime,
    }


def _remote_progress_media(project: Any, task: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    if task.get("status") != "running":
        return {"first_frames": [], "videos": [], "lipsync": []}
    profile_name = _progress_profile_name(project, task)
    if not profile_name:
        return {"first_frames": [], "videos": [], "lipsync": []}
    raw = project.config.remote_profiles.get(profile_name) or {}
    host = str(_task_payload_value(task, "host") or raw.get("host") or "")
    remote_dir = str(_task_payload_value(task, "remote_dir") or raw.get("remote_dir") or "")
    if not host or not remote_dir:
        return {"first_frames": [], "videos": [], "lipsync": []}
    ssh_options = tuple(_profile_string_list(raw.get("ssh_options")))
    first_frames = _cached_remote_files(host, remote_dir, ssh_options, "generated/images", (".png", ".jpg", ".jpeg"))
    videos = _cached_remote_files(host, remote_dir, ssh_options, "generated/clips", (".mp4", ".mov", ".webm"))
    lipsync = _cached_remote_files(host, remote_dir, ssh_options, "generated/lipsync", (".mp4", ".mov", ".webm"))
    if videos:
        _sync_remote_preview_dir(project.config.root, host, remote_dir, ssh_options, "generated/clips")
    if lipsync:
        _sync_remote_preview_dir(project.config.root, host, remote_dir, ssh_options, "generated/lipsync")
    return {
        "first_frames": first_frames,
        "videos": videos,
        "lipsync": lipsync,
    }


def _progress_profile_name(project: Any, task: dict[str, Any]) -> str:
    payload_profile = str(_task_payload_value(task, "profile") or "")
    if payload_profile:
        return payload_profile
    return _first_remote_profile(project) or ""


def _task_payload_value(task: dict[str, Any], key: str) -> Any:
    payload = task.get("payload")
    return payload.get(key) if isinstance(payload, dict) else None


def _cached_remote_files(
    host: str,
    remote_dir: str,
    ssh_options: tuple[str, ...],
    subdir: str,
    suffixes: tuple[str, ...],
) -> list[dict[str, Any]]:
    cache_key = "|".join((host, remote_dir, subdir, ",".join(ssh_options), ",".join(suffixes)))
    now = time.monotonic()
    cached = _REMOTE_PROGRESS_CACHE.get(cache_key)
    if cached and now - cached[0] < REMOTE_PROGRESS_CACHE_TTL_SECONDS:
        return list(cached[1].get("files", []))
    files = _query_remote_files(host, remote_dir, ssh_options, subdir, suffixes)
    _REMOTE_PROGRESS_CACHE[cache_key] = (now, {"files": files})
    return files


def _sync_remote_preview_dir(
    project_root: Path,
    host: str,
    remote_dir: str,
    ssh_options: tuple[str, ...],
    subdir: str,
) -> None:
    cache_key = "|".join((project_root.as_posix(), host, remote_dir, subdir, ",".join(ssh_options)))
    now = time.monotonic()
    last = _REMOTE_PREVIEW_SYNC_CACHE.get(cache_key)
    if last and now - last < REMOTE_PREVIEW_SYNC_CACHE_TTL_SECONDS:
        return
    _REMOTE_PREVIEW_SYNC_CACHE[cache_key] = now
    remote_path = f"{remote_dir.rstrip('/')}/outputs/{subdir.strip('/')}/"
    local_dir = resolve_project_path(project_root, subdir.strip("/"))
    local_dir.mkdir(parents=True, exist_ok=True)
    remote_shell = " ".join(("ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", *_progress_ssh_option_args(ssh_options)))
    command = [
        "rsync",
        "-az",
        "--update",
        "-e",
        remote_shell,
        f"{host}:{remote_path}",
        f"{local_dir.as_posix()}/",
    ]
    try:
        subprocess.run(command, check=False, capture_output=True, text=True, timeout=20)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return


def _query_remote_files(
    host: str,
    remote_dir: str,
    ssh_options: tuple[str, ...],
    subdir: str,
    suffixes: tuple[str, ...],
) -> list[dict[str, Any]]:
    remote_path = f"{remote_dir.rstrip('/')}/outputs/{subdir.strip('/')}"
    suffix_expr = " -o ".join(f"-name '*{suffix}'" for suffix in suffixes)
    command = f"find {shlex.quote(remote_path)} -maxdepth 1 -type f \\( {suffix_expr} \\) -printf '%f|%s|%T@\\n' 2>/dev/null || true"
    args = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", *_progress_ssh_option_args(ssh_options), host, command]
    try:
        completed = subprocess.run(args, check=False, capture_output=True, text=True, timeout=7)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    files: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        parts = line.split("|")
        if len(parts) != 3:
            continue
        name, size, mtime = parts
        stem = Path(name).stem
        try:
            files.append({"name": name, "shot_id": stem, "bytes": int(size), "updated_at": float(mtime)})
        except ValueError:
            files.append({"name": name, "shot_id": stem})
    return sorted(files, key=lambda item: str(item.get("shot_id") or item.get("name") or ""))


def _progress_ssh_option_args(options: tuple[str, ...]) -> list[str]:
    args: list[str] = []
    for option in options:
        args.extend(["-o", option])
    return args


def _video_refresh_ids(project: Any) -> set[str]:
    try:
        plan = plan_jobs(project, kind="video", skip_succeeded=True)
    except AutoVideoError:
        return set()
    return {str(job.get("shot_id")) for job in plan.get("planned", []) if isinstance(job, dict)}


def _audio_refresh_ids(project: Any) -> set[str]:
    try:
        plan = plan_jobs(project, kind="audio", skip_succeeded=True)
    except AutoVideoError:
        return set()
    return {str(job.get("shot_id")) for job in plan.get("planned", []) if isinstance(job, dict)}


def _lipsync_refresh_ids(project: Any) -> set[str]:
    try:
        plan = plan_jobs(project, kind="lipsync", skip_succeeded=True)
    except AutoVideoError:
        return set()
    return {str(job.get("shot_id")) for job in plan.get("planned", []) if isinstance(job, dict)}


def _shot_freshness(shot_id: str, manifest: Any, video_refresh_ids: set[str]) -> dict[str, str]:
    if not isinstance(manifest, dict) or not manifest.get("clip"):
        return {"status": "pending", "message": "尚未生成视频"}
    if shot_id in video_refresh_ids:
        return {"status": "stale", "message": "首帧或引用比视频更新，建议重跑"}
    return {"status": "generated", "message": "视频与当前首帧同步"}


def _audio_freshness(shot_id: str, manifest: Any, audio_refresh_ids: set[str]) -> dict[str, str]:
    if not isinstance(manifest, dict) or not manifest.get("audio"):
        return {"status": "pending", "message": "尚未生成配音"}
    if shot_id in audio_refresh_ids:
        return {"status": "stale", "message": "字幕或配音配置已变化，建议重生成配音"}
    return {"status": "generated", "message": "配音与当前字幕同步"}


def _lipsync_freshness(shot_id: str, manifest: Any, lipsync_refresh_ids: set[str]) -> dict[str, str]:
    if not isinstance(manifest, dict):
        return {"status": "pending", "message": "尚未生成口型同步"}
    if not manifest.get("clip") or not manifest.get("audio"):
        return {"status": "pending", "message": "需先生成视频和配音"}
    if not manifest.get("lipsync_clip"):
        return {"status": "pending", "message": "尚未生成口型同步"}
    if shot_id in lipsync_refresh_ids:
        return {"status": "stale", "message": "视频或配音已变化，建议重跑口型同步"}
    return {"status": "generated", "message": "口型同步与当前视频和配音一致"}


def _remote_profiles_detail(project: Any) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for name, raw in sorted(project.config.remote_profiles.items()):
        details.append(_remote_profile_detail(name, raw))
    return details


def _remote_profile_detail(name: str, raw: dict[str, Any]) -> dict[str, Any]:
    ssh_options = _profile_string_list(raw.get("ssh_options"))
    return {
        "name": name,
        "host": str(raw.get("host") or ""),
        "remote_dir": str(raw.get("remote_dir") or ""),
        "local_dir": str(raw.get("local_dir") or ""),
        "remote_auto_video": str(raw.get("remote_auto_video") or ""),
        "ssh_port": _ssh_port_from_options(ssh_options),
        "ssh_options": ssh_options,
        "rsync_options": _profile_string_list(raw.get("rsync_options")),
        "remote_env": _profile_env_mapping(raw.get("remote_env")),
    }


def _enqueue_project_task(
    queue: WebTaskQueue,
    project_name: str,
    project_root: Path,
    request_payload: dict[str, Any],
) -> dict[str, Any]:
    action = str(request_payload.get("action") or "").strip()
    if not action:
        raise ConfigError("task action is required", fix="Choose a production action.")
    payload = _task_payload(request_payload)
    label = str(request_payload.get("label") or ACTION_LABELS.get(action, action))

    def runner(log: TaskLogger) -> Any:
        return _run_project_action(project_root, action, payload, log=log)

    return queue.enqueue(project=project_name, action=action, label=label, payload=payload, runner=runner)


def _task_payload(request_payload: dict[str, Any]) -> dict[str, Any]:
    raw_payload = request_payload.get("payload")
    if raw_payload is None:
        raw_payload = {key: value for key, value in request_payload.items() if key not in {"action", "label"}}
    if not isinstance(raw_payload, dict):
        raise ConfigError("task payload must be an object", fix="Send payload as a JSON object.")
    return raw_payload


def _run_project_action(
    project_root: Path,
    action: str,
    payload: dict[str, Any],
    *,
    log: TaskLogger | None = None,
) -> Any:
    logger = log or (lambda _message: None)
    if action not in ACTION_LABELS:
        raise ConfigError("unsupported task action", fix=f"Use one of: {', '.join(sorted(ACTION_LABELS))}.")
    if action == "validate":
        logger("读取项目配置并执行结构校验")
        warnings = validate_project(load_project(project_root))
        logger(f"校验完成，警告 {len(warnings)} 条")
        return {"warnings": warnings, "warning_count": len(warnings)}
    if action == "jobs-plan":
        project = load_project(project_root)
        logger("根据分镜和 provider 生成任务计划")
        result = plan_jobs(
            project,
            kind=str(payload.get("kind") or "video"),
            provider_name=payload.get("provider") or None,
            only=_payload_only(payload),
            failed_only=bool(payload.get("failed_only", False)),
            skip_succeeded=bool(payload.get("skip_succeeded", False)),
        )
        logger(f"计划任务 {len(result.get('planned', []))} 个")
        return result
    if action == "lipsync-plan":
        project = load_project(project_root)
        logger("根据已生成视频和配音生成口型同步计划")
        result = plan_jobs(
            project,
            kind="lipsync",
            provider_name=payload.get("provider") or project.config.default_lipsync_provider,
            only=_payload_only(payload),
            failed_only=bool(payload.get("failed_only", False)),
            skip_succeeded=bool(payload.get("skip_succeeded", True)),
        )
        logger(f"计划口型同步任务 {len(result.get('planned', []))} 个")
        return result
    if action == "generate":
        project = load_project(project_root)
        kind = str(payload.get("kind") or "video")
        logger(f"开始提交 {kind} 生成任务")
        results = submit_jobs(
            project,
            kind=kind,
            provider_name=payload.get("provider") or None,
            only=_payload_only(payload),
            failed_only=bool(payload.get("failed_only", False)),
            skip_succeeded=bool(payload.get("skip_succeeded", False)),
        )
        logger(f"生成执行完成，共返回 {len(results)} 个结果")
        return {
            "count": len(results),
            "submitted": [_provider_result_summary(result, project.config.root) for result in results],
        }
    if action == "lipsync":
        project = load_project(project_root)
        logger("开始执行口型同步任务")
        results = submit_jobs(
            project,
            kind="lipsync",
            provider_name=payload.get("provider") or project.config.default_lipsync_provider,
            only=_payload_only(payload),
            failed_only=bool(payload.get("failed_only", False)),
            skip_succeeded=bool(payload.get("skip_succeeded", True)),
        )
        logger(f"口型同步完成，共返回 {len(results)} 个结果")
        return {
            "count": len(results),
            "submitted": [_provider_result_summary(result, project.config.root) for result in results],
        }
    if action == "first-frame-generate":
        project = load_project(project_root)
        logger("开始生成首帧图片")
        result = generate_first_frames(
            project,
            provider_name=payload.get("provider") or None,
            only=_payload_only(payload),
            failed_only=bool(payload.get("failed_only", False)),
            skip_succeeded=bool(payload.get("skip_succeeded", False)),
        )
        logger(f"首帧生成完成，已绑定 {result.get('first_frames', {}).get('count', 0)} 张")
        return result
    if action == "probe":
        logger("开始检查生成媒体")
        result = probe_project(
            load_project(project_root),
            dry_run=bool(payload.get("dry_run", False)),
            blackdetect=bool(payload.get("blackdetect", False)),
        )
        summary = result.get("summary", {}) if isinstance(result, dict) else {}
        logger(f"验片完成，通过 {summary.get('passed', 0)}，失败 {summary.get('failed', 0)}")
        return result
    if action == "assemble-plan":
        logger("生成合成预案")
        return assemble_project(load_project(project_root), dry_run=True)
    if action == "assemble":
        logger("开始合成成片")
        return assemble_project(load_project(project_root), dry_run=bool(payload.get("dry_run", False)))
    if action == "continuity":
        logger("提取已生成视频的尾帧，用于后续镜头连续性")
        result = extract_tail_frames(
            load_project(project_root),
            dry_run=bool(payload.get("dry_run", False)),
            force=bool(payload.get("force", False)),
        )
        logger(f"连续性尾帧完成，新增 {len(result.get('extracted', []))} 个，跳过 {len(result.get('skipped', []))} 个")
        return result
    if action == "novel-draft":
        logger("读取章节正文并准备 Codex 分析")
        result = draft_novel_chapter(load_project(project_root), payload)
        meta = result.get("meta", {}) if isinstance(result, dict) else {}
        logger(
            "章节草稿完成："
            f"{meta.get('shot_count', 0)} 个分镜，"
            f"{meta.get('target_minutes', 0)} 分钟，"
            f"分析器 {meta.get('analyzer', 'rules')}"
        )
        return result
    if action == "produce-all":
        return _run_full_production(project_root, payload, logger)
    if action == "remote-wrapup":
        project = load_project(project_root)
        result = _run_remote_wrapup(project, payload)
        logger("远程收尾检查完成")
        return result
    if action == "comfyui-check":
        project = load_project(project_root)
        profile = str(payload.get("profile") or _first_workflow_profile(project, kind=str(payload.get("kind") or "image_to_video")))
        logger(f"检查 ComfyUI 工作流：{profile}")
        return _run_comfyui_check(project, profile, payload)
    if action in {"remote-plan", "remote-run", "remote-first-frame"}:
        project = load_project(project_root)
        logger("构建远程执行参数")
        kind = "image" if action == "remote-first-frame" else str(payload.get("kind") or "video")
        provider_name = payload.get("provider") or _default_provider_for_kind(project, kind, prefer_comfy_video=True)
        options = build_remote_run_options_from_profile(
            project,
            profile_name=payload.get("profile") or None,
            host=payload.get("host") or None,
            remote_dir=payload.get("remote_dir") or None,
            provider_name=provider_name,
            kind=kind,
            only=_payload_only(payload),
            failed_only=bool(payload.get("failed_only", False)),
            skip_succeeded=bool(payload.get("skip_succeeded", False)),
            local_dir=Path(str(payload["local_dir"])) if payload.get("local_dir") else None,
            remote_auto_video=payload.get("remote_auto_video") or None,
            ssh_options=_string_tuple(payload.get("ssh_options"), field_name="ssh_options"),
            rsync_options=_string_tuple(payload.get("rsync_options"), field_name="rsync_options"),
            remote_env=_remote_env_items(payload.get("remote_env")),
        )
        dry_run = action == "remote-plan" or bool(payload.get("dry_run", False))
        logger("远程预案生成中" if dry_run else "远程首帧生成中" if action == "remote-first-frame" else "远程任务执行中")
        result = run_remote_worker(project, options, dry_run=dry_run)
        if action == "remote-first-frame" and not dry_run:
            first_frames = promote_generated_images_to_first_frames(load_project(project_root), only=_payload_only(payload))
            result = {**result, "first_frames": first_frames}
            logger(f"远程首帧已导回并绑定 {first_frames.get('count', 0)} 张")
        return result
    raise ConfigError("unsupported task action", fix=f"Use one of: {', '.join(sorted(ACTION_LABELS))}.")


def _run_full_production(project_root: Path, payload: dict[str, Any], logger: TaskLogger) -> dict[str, Any]:
    project = load_project(project_root)
    steps: list[dict[str, Any]] = []
    remote_profile = str(payload.get("profile") or _first_remote_profile(project) or "")
    use_remote = bool(remote_profile) and not bool(payload.get("local_only", False))

    logger("步骤 1/7：校验项目")
    warnings = validate_project(project)
    steps.append({"step": "validate", "warning_count": len(warnings), "warnings": warnings})

    if not bool(payload.get("skip_first_frames", False)):
        logger("步骤 2/7：生成或补齐首帧")
        if use_remote and project.config.default_image_provider != "mock":
            image_result = _run_remote_generation(
                project,
                profile=remote_profile,
                provider=project.config.default_image_provider,
                kind="image",
                payload=payload,
                skip_succeeded=True,
            )
            first_frames = promote_generated_images_to_first_frames(load_project(project_root), only=_payload_only(payload))
            image_result = {**image_result, "first_frames": first_frames}
        else:
            image_result = generate_first_frames(
                project,
                provider_name=payload.get("image_provider") or project.config.default_image_provider,
                only=_payload_only(payload),
                skip_succeeded=True,
            )
        steps.append({"step": "first_frames", "result": image_result})

    project = load_project(project_root)
    logger("步骤 3/7：生成缺失或过期分镜视频")
    if use_remote and project.config.default_video_provider != "mock":
        video_result = _run_remote_generation(
            project,
            profile=remote_profile,
            provider=payload.get("provider") or project.config.default_video_provider,
            kind="video",
            payload=payload,
            skip_succeeded=True,
        )
    else:
        video_results = submit_jobs(
            project,
            kind="video",
            provider_name=payload.get("provider") or project.config.default_video_provider,
            only=_payload_only(payload),
            skip_succeeded=True,
        )
        video_result = {"count": len(video_results), "submitted": [_provider_result_summary(result, project.config.root) for result in video_results]}
    steps.append({"step": "videos", "result": video_result})

    project = load_project(project_root)
    if not bool(payload.get("skip_voiceover", False)):
        logger("步骤 4/7：生成缺失或过期配音")
        audio_results = submit_jobs(
            project,
            kind="audio",
            provider_name=payload.get("audio_provider") or project.config.default_audio_provider,
            only=_payload_only(payload),
            skip_succeeded=True,
        )
        audio_result = {"count": len(audio_results), "submitted": [_provider_result_summary(result, project.config.root) for result in audio_results]}
        steps.append({"step": "voiceover", "result": audio_result})
    else:
        logger("步骤 4/7：跳过配音")
        steps.append({"step": "voiceover", "skipped": True})

    project = load_project(project_root)
    if not bool(payload.get("skip_lipsync", False)):
        logger("步骤 5/7：执行口型同步")
        lipsync_provider = payload.get("lipsync_provider") or project.config.default_lipsync_provider
        if use_remote and lipsync_provider != "mock":
            lipsync_result = _run_remote_generation(
                project,
                profile=remote_profile,
                provider=lipsync_provider,
                kind="lipsync",
                payload=payload,
                skip_succeeded=True,
            )
        else:
            lipsync_results = submit_jobs(
                project,
                kind="lipsync",
                provider_name=lipsync_provider,
                only=_payload_only(payload),
                skip_succeeded=True,
            )
            lipsync_result = {
                "count": len(lipsync_results),
                "submitted": [_provider_result_summary(result, project.config.root) for result in lipsync_results],
            }
        steps.append({"step": "lipsync", "result": lipsync_result})
    else:
        logger("步骤 5/7：跳过口型同步")
        steps.append({"step": "lipsync", "skipped": True})

    project = load_project(project_root)
    logger("步骤 6/7：自动验片")
    probe = probe_project(
        project,
        dry_run=bool(payload.get("probe_dry_run", project.config.default_video_provider == "mock")),
        blackdetect=bool(payload.get("blackdetect", True)),
    )
    steps.append({"step": "probe", "summary": probe.get("summary", {}), "result": probe})

    project = load_project(project_root)
    if not bool(payload.get("skip_assemble", False)):
        logger("步骤 7/7：合成成片")
        render = assemble_project(project, dry_run=bool(payload.get("dry_run", project.config.default_video_provider == "mock")))
        steps.append({"step": "assemble", "result": render})
    else:
        logger("步骤 7/7：跳过合成")
        steps.append({"step": "assemble", "skipped": True})

    if bool(payload.get("extract_continuity", True)):
        project = load_project(project_root)
        continuity = extract_tail_frames(
            project,
            dry_run=bool(payload.get("dry_run", project.config.default_video_provider == "mock")),
            force=True,
        )
        steps.append({"step": "continuity", "result": continuity})

    return {"project": project.config.name, "remote": use_remote, "profile": remote_profile or None, "steps": steps}


def _run_remote_generation(
    project: Any,
    *,
    profile: str,
    provider: str,
    kind: str,
    payload: dict[str, Any],
    skip_succeeded: bool,
) -> dict[str, Any]:
    if skip_succeeded and not bool(payload.get("dry_run", False)):
        plan = plan_jobs(project, kind=kind, provider_name=provider, only=_payload_only(payload), skip_succeeded=True)
        if not plan.get("planned"):
            return {"skipped": True, "reason": "no_missing_or_stale_jobs", "planned": []}
    options = build_remote_run_options_from_profile(
        project,
        profile_name=profile,
        host=payload.get("host") or None,
        remote_dir=payload.get("remote_dir") or None,
        provider_name=provider,
        kind=kind,
        only=_payload_only(payload),
        failed_only=False,
        skip_succeeded=skip_succeeded,
        local_dir=Path(str(payload["local_dir"])) if payload.get("local_dir") else None,
        remote_auto_video=payload.get("remote_auto_video") or None,
        ssh_options=_string_tuple(payload.get("ssh_options"), field_name="ssh_options"),
        rsync_options=_string_tuple(payload.get("rsync_options"), field_name="rsync_options"),
        remote_env=_remote_env_items(payload.get("remote_env")),
    )
    return run_remote_worker(project, options, dry_run=bool(payload.get("dry_run", False)))


def _first_remote_profile(project: Any) -> str | None:
    names = sorted(project.config.remote_profiles)
    return names[0] if names else None


def _run_remote_wrapup(project: Any, payload: dict[str, Any]) -> dict[str, Any]:
    profile = str(payload.get("profile") or _first_remote_profile(project) or "")
    if not profile:
        raise ConfigError("项目没有远程配置", fix="请先在工作流配置里填写 AutoDL SSH 信息。")
    options = build_remote_run_options_from_profile(
        project,
        profile_name=profile,
        host=payload.get("host") or None,
        remote_dir=payload.get("remote_dir") or None,
        provider_name=payload.get("provider") or project.config.default_video_provider,
        kind=str(payload.get("kind") or "video"),
        only=None,
        failed_only=False,
        skip_succeeded=True,
        local_dir=Path(str(payload["local_dir"])) if payload.get("local_dir") else None,
        remote_auto_video=payload.get("remote_auto_video") or None,
        ssh_options=_string_tuple(payload.get("ssh_options"), field_name="ssh_options"),
        rsync_options=_string_tuple(payload.get("rsync_options"), field_name="rsync_options"),
        remote_env=_remote_env_items(payload.get("remote_env")),
    )
    env = dict(item.split("=", 1) for item in options.remote_env if "=" in item)
    comfyui_base_url = str(payload.get("comfyui_base_url") or env.get("COMFYUI_BASE_URL") or "http://127.0.0.1:6006")
    return run_remote_wrapup(
        RemoteWrapupOptions(
            host=options.host,
            remote_dir=options.remote_dir,
            ssh_options=options.ssh_options,
            comfyui_base_url=comfyui_base_url,
        ),
        dry_run=bool(payload.get("dry_run", False)),
    )


def _first_workflow_profile(project: Any, *, kind: str | None = None) -> str:
    names = sorted(project.config.comfyui_workflows)
    if not names:
        raise ConfigError("项目没有配置 ComfyUI 工作流", fix="请在项目配置中添加 comfyui_workflows。")
    if kind:
        for name in names:
            raw = project.config.comfyui_workflows.get(name) or {}
            if str(raw.get("kind") or "") == kind:
                return name
    return names[0]


def _run_comfyui_check(project: Any, profile: str, payload: dict[str, Any]) -> dict[str, Any]:
    workflow = project.config.comfyui_workflows.get(profile) or {}
    workflow_kind = str(payload.get("kind") or workflow.get("kind") or "")
    is_image_workflow = workflow_kind in {"image", "text_to_image", "first_frame"} or str(workflow.get("provider") or "") == project.config.default_image_provider
    is_lipsync_workflow = workflow_kind in {"lipsync", "lip_sync", "audio_to_video"}
    if is_lipsync_workflow:
        options = comfyui_lipsync_adapter_options(project, profile)
    else:
        options = comfyui_image_adapter_options(project, profile) if is_image_workflow else comfyui_wan_adapter_options(project, profile)
    workflow_path = payload.get("workflow") or options.get("workflow")
    args = Namespace(
        mode="lipsync" if is_lipsync_workflow else "image" if is_image_workflow else "wan_video",
        base_url=payload.get("base_url") or options.get("base_url"),
        base_url_env=options.get("base_url_env"),
        workflow=_runtime_workflow_path(project, workflow_path),
        workflow_env=options.get("workflow_env"),
        timeout=float(payload.get("timeout") or 15),
        require_gpu=bool(payload.get("require_gpu", False)),
        require_idle=bool(payload.get("require_idle", False)),
        image_node=options.get("image_node", "224"),
        image_input=options.get("image_input", "image"),
        prompt_node=options.get("prompt_node", "187" if is_image_workflow else "257"),
        prompt_input=options.get("prompt_input", "text" if is_image_workflow else "value"),
        negative_node=options.get("negative_node", "437" if is_image_workflow else "218"),
        negative_input=options.get("negative_input", "text"),
        seed_node=options.get("seed_node", "3" if is_image_workflow else "231"),
        seed_input=options.get("seed_input", "seed"),
        size_node=options.get("size_node", "118"),
        width_input=options.get("width_input", "width"),
        height_input=options.get("height_input", "height"),
        output_node=options.get("output_node", "output" if is_lipsync_workflow else "499"),
        duration_node=options.get("duration_node", "238"),
        duration_input=options.get("duration_input", "value"),
        resolution_node=options.get("resolution_node", "248"),
        resolution_input=options.get("resolution_input", "value"),
        video_node=options.get("video_node", "video" if is_lipsync_workflow else "230"),
        video_input=options.get("video_input", "video"),
        audio_node=options.get("audio_node", "audio"),
        audio_input=options.get("audio_input", "audio"),
        frame_rate_input=options.get("frame_rate_input", "frame_rate"),
        filename_prefix_input=options.get("filename_prefix_input", "filename_prefix"),
        steps_node=options.get("steps_node", [] if is_lipsync_workflow else ["3"] if is_image_workflow else ["228", "229"]),
        steps_input=options.get("steps_input", "steps"),
        cfg_input=options.get("cfg_input", "cfg"),
    )
    report = run_comfyui_doctor(args)
    return {"profile": profile, **report}


def _runtime_workflow_path(project: Any, value: Any) -> str | None:
    if not value:
        return None
    path = Path(str(value))
    if path.is_absolute():
        return path.as_posix()
    return (project.config.root / path).resolve().as_posix()


def _default_provider_for_kind(project: Any, kind: str, *, prefer_comfy_video: bool = False) -> str:
    if kind == "image":
        return project.config.default_image_provider
    if kind == "audio":
        return project.config.default_audio_provider
    if kind == "lipsync":
        return project.config.default_lipsync_provider
    if prefer_comfy_video and "comfyui_wan" in project.config.providers:
        return "comfyui_wan"
    return project.config.default_video_provider


def _payload_only(payload: dict[str, Any]) -> set[str] | None:
    value = payload.get("only")
    if not value:
        return None
    if isinstance(value, str):
        return {item.strip() for item in value.split(",") if item.strip()}
    if isinstance(value, list):
        return {str(item).strip() for item in value if str(item).strip()}
    raise ConfigError("only must be a comma-separated string or list", fix="Use shot ids such as S01,S02.")


def _remote_env_items(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, dict):
        return tuple(f"{key}={item}" for key, item in value.items())
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    raise ConfigError("remote_env must be an object or list", fix="Use KEY=value entries.")


def _string_tuple(value: Any, *, field_name: str) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    raise ConfigError(f"{field_name} must be a string or list", fix="Use command-line style option strings.")


def _provider_result_summary(result: Any, root: Path) -> dict[str, Any]:
    path = result.path
    if path is not None:
        try:
            path_text = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            path_text = path.as_posix()
    else:
        path_text = None
    return {
        "job_id": result.job_id,
        "shot_id": result.shot_id,
        "kind": result.kind,
        "provider": result.provider,
        "status": result.status,
        "path": path_text,
        "duration": result.duration,
        "provider_job_id": result.provider_job_id,
        "error": result.error,
        "retryable": result.retryable,
        "metadata": result.metadata,
    }


def _delete_project(root: Path, tasks: list[dict[str, Any]]) -> None:
    if not root.exists() or not root.is_dir():
        raise ConfigError("project not found", fix="Refresh the project list.")
    active = [task for task in tasks if task.get("status") in {"queued", "running"}]
    if active:
        raise ConfigError("project has active tasks", fix="Wait for running tasks to finish or cancel queued tasks before deleting.")
    shutil.rmtree(root)


def _ensure_project_exists(root: Path) -> None:
    if not root.exists() or not root.is_dir() or not (root / "project.yaml").exists() or not (root / "shots.json").exists():
        raise ConfigError("项目不存在或配置缺失", fix="请从左侧选择现有项目，或重新新建项目。")


def _project_path(workspace: Path, name: str) -> Path:
    if not name or not PROJECT_NAME_RE.match(name):
        raise ConfigError(
            "invalid project name",
            fix="Use letters, numbers, dash, underscore, or dot.",
        )
    candidate = (workspace / name).resolve()
    if workspace != candidate and workspace not in candidate.parents:
        raise ConfigError("project path escapes workspace", fix="Choose a project inside the web workspace.")
    return candidate


def _write_project_config(root: Path, text: str) -> None:
    path = root / "project.yaml"
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(text, encoding="utf-8")
    try:
        validate_project(load_project(root))
    except Exception:
        path.write_text(old, encoding="utf-8")
        raise


def _update_prompt_profile(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    config_path = root / "project.yaml"
    old_config = config_path.read_text(encoding="utf-8")
    data = yaml.safe_load(old_config) or {}
    if not isinstance(data, dict):
        raise ConfigError("project.yaml must contain a mapping", fix="Restore a valid project.yaml.")

    profile = data.setdefault("prompt_profile", {})
    if not isinstance(profile, dict):
        raise ConfigError("prompt_profile must be a mapping", fix="Use key/value prompt continuity fields.")
    for key in PROMPT_PROFILE_KEYS:
        if key not in payload:
            continue
        value = str(payload.get(key) or "").strip()
        if value:
            profile[key] = value
        else:
            profile.pop(key, None)
    if not profile:
        data.pop("prompt_profile", None)

    try:
        config_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        project = load_project(root)
        validate_project(project)
    except Exception:
        config_path.write_text(old_config, encoding="utf-8")
        raise
    return {"prompt_profile": asdict(project.config.prompt_profile)}


def _update_workflow_settings(root: Path, profile: str, payload: dict[str, Any]) -> dict[str, Any]:
    profile = profile.strip()
    if not profile:
        raise ConfigError("workflow profile is required", fix="Choose a workflow profile.")
    config_path = root / "project.yaml"
    old_config = config_path.read_text(encoding="utf-8")
    old_files: dict[Path, bytes | None] = {}

    data = yaml.safe_load(old_config) or {}
    if not isinstance(data, dict):
        raise ConfigError("project.yaml must contain a mapping", fix="Restore a valid project.yaml.")
    workflows = data.setdefault("comfyui_workflows", {})
    if not isinstance(workflows, dict):
        raise ConfigError("comfyui_workflows must be a mapping", fix="Use workflow profile names as keys.")
    if profile not in workflows or not isinstance(workflows[profile], dict):
        raise ConfigError(f"工作流配置不存在：{profile}", fix="请先在 project.yaml 的 comfyui_workflows 中添加该配置。")

    raw = workflows[profile]
    base_url = str(payload.get("base_url") or "").strip()
    workflow_path = str(payload.get("workflow_path") or "").strip()
    workflow_json = payload.get("workflow_json")

    if "base_url" in payload:
        if base_url:
            raw["base_url"] = base_url.rstrip("/")
        else:
            raw.pop("base_url", None)
    if workflow_json is not None and str(workflow_json).strip():
        workflow_path = _save_workflow_json(root, profile, payload, str(workflow_json), old_files)
        raw["workflow_path"] = workflow_path
    elif "workflow_path" in payload:
        if workflow_path:
            raw["workflow_path"] = workflow_path
        else:
            raw.pop("workflow_path", None)

    _sync_workflow_env(data, profile, raw)

    try:
        config_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        validate_project(load_project(root))
    except Exception:
        config_path.write_text(old_config, encoding="utf-8")
        for path, body in old_files.items():
            if body is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
        raise
    return {"workflow": raw}


def _update_remote_profile(root: Path, profile: str, payload: dict[str, Any]) -> dict[str, Any]:
    profile = profile.strip()
    if not profile:
        raise ConfigError("remote profile is required", fix="Choose a remote profile.")
    config_path = root / "project.yaml"
    old_config = config_path.read_text(encoding="utf-8")

    data = yaml.safe_load(old_config) or {}
    if not isinstance(data, dict):
        raise ConfigError("project.yaml must contain a mapping", fix="Restore a valid project.yaml.")
    profiles = data.setdefault("remote_profiles", {})
    if not isinstance(profiles, dict):
        raise ConfigError("remote_profiles must be a mapping", fix="Use profile names as keys.")
    if profile not in profiles or not isinstance(profiles[profile], dict):
        raise ConfigError(f"远程配置不存在：{profile}", fix="请先在 project.yaml 的 remote_profiles 中添加该配置。")

    raw = profiles[profile]
    for key in ("host", "remote_dir", "local_dir", "remote_auto_video"):
        if key not in payload:
            continue
        value = str(payload.get(key) or "").strip()
        if value:
            raw[key] = value
        else:
            raw.pop(key, None)
    if "ssh_port" in payload:
        ssh_options = _with_ssh_port(_profile_string_list(raw.get("ssh_options")), payload.get("ssh_port"))
        if ssh_options:
            raw["ssh_options"] = ssh_options
        else:
            raw.pop("ssh_options", None)

    try:
        config_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        project = load_project(root)
        validate_project(project)
        _validate_remote_profile_if_ready(project, profile)
    except Exception:
        config_path.write_text(old_config, encoding="utf-8")
        raise
    return {"profile": _remote_profile_detail(profile, raw)}


def _validate_remote_profile_if_ready(project: Any, profile: str) -> None:
    raw = project.config.remote_profiles.get(profile, {})
    host = str(raw.get("host") or "")
    remote_dir = str(raw.get("remote_dir") or "")
    if not _profile_value_ready(host) or not _profile_value_ready(remote_dir):
        return
    options = build_remote_run_options_from_profile(
        project,
        profile_name=profile,
        host=None,
        remote_dir=None,
        provider_name="comfyui_wan",
        kind="video",
        only=None,
        failed_only=False,
        skip_succeeded=False,
        local_dir=None,
        remote_auto_video=None,
        ssh_options=(),
        rsync_options=(),
        remote_env=(),
    )
    run_remote_worker(project, options, dry_run=True)


def _profile_value_ready(value: str) -> bool:
    return bool(value.strip()) and "<" not in value and ">" not in value


def _profile_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _profile_env_mapping(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(key): str(env_value) for key, env_value in value.items()}
    if isinstance(value, list):
        result: dict[str, str] = {}
        for item in value:
            text = str(item)
            if "=" in text:
                key, env_value = text.split("=", 1)
                result[key] = env_value
        return result
    return {}


def _ssh_port_from_options(options: list[str]) -> str:
    for option in options:
        value = option.strip()
        lower = value.lower()
        port = ""
        if lower.startswith("port="):
            port = value.split("=", 1)[1].strip()
        elif lower.startswith("port "):
            port = value.split(None, 1)[1].strip()
        if port and "<" not in port and ">" not in port:
            return port
    return ""


def _with_ssh_port(options: list[str], port: Any) -> list[str]:
    kept = [option for option in options if not _is_ssh_port_option(option)]
    port_text = str(port or "").strip()
    if not port_text:
        return kept
    if not port_text.isdigit():
        raise ConfigError("SSH 端口必须是数字", fix="请填写 AutoDL 实例 SSH 命令中的 -p 端口，例如 13159。")
    port_number = int(port_text)
    if port_number < 1 or port_number > 65535:
        raise ConfigError("SSH 端口超出范围", fix="请填写 1 到 65535 之间的端口。")
    return [*kept, f"Port={port_number}"]


def _is_ssh_port_option(option: str) -> bool:
    lower = option.strip().lower()
    return lower.startswith("port=") or lower.startswith("port ")


def _save_workflow_json(root: Path, profile: str, payload: dict[str, Any], raw_json: str, old_files: dict[Path, bytes | None]) -> str:
    body = raw_json.encode("utf-8")
    if len(body) > MAX_WORKFLOW_JSON_BYTES:
        raise ConfigError("workflow JSON is too large", fix="Use a workflow JSON smaller than 5 MB.")
    try:
        workflow = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ConfigError("workflow JSON 格式错误", fix=f"请上传 ComfyUI 导出的 API JSON。{exc.msg}") from exc
    if not isinstance(workflow, dict):
        raise ConfigError("workflow JSON must contain an object", fix="请上传 ComfyUI 导出的 API JSON 对象。")
    filename = str(payload.get("workflow_filename") or f"{profile}.json")
    safe_stem = _safe_asset_name(Path(filename).stem or profile)
    output = (root / "workflows" / f"{safe_stem}.json").resolve()
    if root.resolve() not in output.parents:
        raise ConfigError("workflow path escapes project root", fix="Use a workflow JSON filename without path segments.")
    if output not in old_files:
        old_files[output] = output.read_bytes() if output.exists() else None
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output.relative_to(root.resolve()).as_posix()


def _sync_workflow_env(data: dict[str, Any], profile: str, raw: dict[str, Any]) -> None:
    provider_name = str(raw.get("provider") or "comfyui_wan")
    base_url_env = str(raw.get("base_url_env") or "COMFYUI_BASE_URL")
    workflow_env = str(raw.get("workflow_env") or "COMFYUI_WORKFLOW")
    profile_env = str(raw.get("profile_env") or "COMFYUI_WORKFLOW_PROFILE")
    assignments = {
        base_url_env: raw.get("base_url"),
        workflow_env: raw.get("workflow_path"),
        profile_env: profile,
    }

    providers = data.setdefault("providers", {})
    if isinstance(providers, dict):
        provider = providers.setdefault(provider_name, {})
        if isinstance(provider, dict):
            provider_env = provider.setdefault("env", {})
            if isinstance(provider_env, dict):
                _update_env_mapping(provider_env, assignments)

    remote_profiles = data.get("remote_profiles")
    if isinstance(remote_profiles, dict):
        for remote_profile in remote_profiles.values():
            if not isinstance(remote_profile, dict):
                continue
            remote_env = remote_profile.setdefault("remote_env", {})
            if isinstance(remote_env, dict):
                _update_env_mapping(remote_env, assignments)


def _update_env_mapping(env: dict[str, Any], assignments: dict[str, Any]) -> None:
    for key, value in assignments.items():
        if value:
            env[key] = str(value)
        else:
            env.pop(key, None)


def _write_shots(root: Path, shots: Any) -> None:
    if not isinstance(shots, list) or not shots:
        raise ConfigError("shots payload must be a non-empty list", fix="Keep at least one shot.")
    path = root / "shots.json"
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(json.dumps({"shots": shots}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        validate_project(load_project(root))
    except Exception:
        path.write_text(old, encoding="utf-8")
        raise


def _update_shot_refs(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    shot_id = str(payload.get("shot_id") or "").strip()
    if not shot_id:
        raise ConfigError("shot_id is required", fix="请选择要绑定素材的分镜。")
    refs = _sanitize_refs(payload.get("refs"))
    shots_path = root / "shots.json"
    data = json.loads(shots_path.read_text(encoding="utf-8"))
    shots = data.get("shots")
    if not isinstance(shots, list):
        raise ConfigError("shots.json must contain shots", fix="Restore a valid shots.json.")
    for shot in shots:
        if str(shot.get("id")) != shot_id:
            continue
        shot["refs"] = refs
        _write_shots(root, shots)
        return {"shot_id": shot_id, "refs": refs}
    raise ConfigError(f"shot {shot_id} not found", fix="Refresh the project and choose an existing shot.")


def _sanitize_refs(raw_refs: Any) -> list[dict[str, str]]:
    if raw_refs is None:
        return []
    if not isinstance(raw_refs, list):
        raise ConfigError("refs must be a list", fix="请提交素材引用数组。")
    clean_refs: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for raw in raw_refs:
        if not isinstance(raw, dict):
            raise ConfigError("ref must be an object", fix="每个素材引用都需要 path/type/role/usage。")
        clean = {
            "path": str(raw.get("path") or "").strip(),
            "type": str(raw.get("type") or "").strip(),
            "role": str(raw.get("role") or "").strip(),
            "usage": str(raw.get("usage") or "").strip(),
        }
        if not clean["path"]:
            raise ConfigError("ref path is required", fix="素材引用缺少路径。")
        AssetRef(**clean)
        if clean["path"] in seen_paths:
            continue
        seen_paths.add(clean["path"])
        clean_refs.append(clean)
    return clean_refs


def _remove_asset_refs(root: Path, relative_path: str) -> None:
    if not relative_path:
        return
    shots_path = root / "shots.json"
    data = json.loads(shots_path.read_text(encoding="utf-8"))
    shots = data.get("shots")
    if not isinstance(shots, list):
        return
    changed = False
    for shot in shots:
        refs = shot.get("refs")
        if not isinstance(refs, list):
            continue
        next_refs = [ref for ref in refs if not (isinstance(ref, dict) and ref.get("path") == relative_path)]
        if len(next_refs) != len(refs):
            shot["refs"] = next_refs
            changed = True
    if changed:
        _write_shots(root, shots)


def _apply_script_storyboard(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    shots = payload.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ConfigError("脚本分镜不能为空", fix="请先生成分镜草稿，再应用到项目。")
    shots_path = root / "shots.json"
    manifest_path = root / "manifest.json"
    old_shots = shots_path.read_text(encoding="utf-8") if shots_path.exists() else ""
    old_manifest = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else None
    try:
        _write_shots(root, shots)
        if bool(payload.get("reset_manifest", True)):
            _reset_generation_manifest(root)
    except Exception:
        if old_shots:
            shots_path.write_text(old_shots, encoding="utf-8")
        if old_manifest is None:
            manifest_path.unlink(missing_ok=True)
        else:
            manifest_path.write_text(old_manifest, encoding="utf-8")
        raise
    return {"applied": len(shots)}


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


def _upload_first_frame(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    shot_id = str(payload.get("shot_id") or "").strip()
    filename = str(payload.get("filename") or f"{shot_id}_first_frame.png").strip()
    data_url = str(payload.get("data_url") or "")
    if not shot_id:
        raise ConfigError("shot_id is required", fix="Choose a shot before uploading.")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".png"
    encoded = data_url.split(",", 1)[1] if "," in data_url else str(payload.get("data_base64") or "")
    body = base64.b64decode(encoded, validate=True)
    if len(body) > MAX_UPLOAD_BYTES:
        raise ConfigError("upload is too large", fix="Use an image smaller than 20 MB.")
    safe_name = f"{_safe_asset_name(shot_id)}_first_frame{suffix}"
    relative_path = f"assets/refs/{safe_name}"
    output = root / relative_path
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(body)
    _set_first_frame_ref(root, shot_id, relative_path)
    return {"path": relative_path, "bytes": len(body)}


def _set_first_frame_ref(root: Path, shot_id: str, relative_path: str) -> None:
    shots_path = root / "shots.json"
    data = json.loads(shots_path.read_text(encoding="utf-8"))
    shots = data.get("shots")
    if not isinstance(shots, list):
        raise ConfigError("shots.json must contain shots", fix="Restore a valid shots.json.")
    found = False
    for shot in shots:
        if str(shot.get("id")) != shot_id:
            continue
        refs = shot.setdefault("refs", [])
        if not isinstance(refs, list):
            refs = []
            shot["refs"] = refs
        for ref in refs:
            if isinstance(ref, dict) and ref.get("type") == "image" and ref.get("role") == "first_frame":
                ref["path"] = relative_path
                found = True
                break
        if not found:
            refs.insert(
                0,
                {
                    "path": relative_path,
                    "type": "image",
                    "role": "first_frame",
                    "usage": "preserve_subject",
                },
            )
            found = True
        break
    if not found:
        raise ConfigError(f"shot {shot_id} not found", fix="Refresh the project and choose an existing shot.")
    _write_shots(root, shots)


def _safe_asset_name(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value).strip("_")
    return safe or "shot"


APP_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Auto AI Video Console</title>
  <link rel="stylesheet" href="/app.css">
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div>
        <div class="brand">Auto AI Video</div>
        <div class="workspace" id="workspace"></div>
      </div>
      <form id="createForm" class="create-row">
        <input id="projectName" name="name" placeholder="new_project" autocomplete="off">
        <select id="templateSelect" name="template"></select>
        <button type="submit">新建</button>
      </form>
    </header>
    <main class="layout">
      <aside class="sidebar">
        <div class="panel-title">项目</div>
        <div id="projectList" class="project-list"></div>
      </aside>
      <section class="main">
        <div id="emptyState" class="empty">选择或创建一个项目</div>
        <div id="projectView" class="hidden">
          <div class="summary-band">
            <div>
              <div class="eyebrow">PROJECT</div>
              <h1 id="projectTitle"></h1>
            </div>
            <div class="metrics" id="metrics"></div>
          </div>
          <nav class="tabs">
            <button data-tab="shots" class="active">分镜</button>
            <button data-tab="workflow">Workflow</button>
            <button data-tab="actions">运行</button>
            <button data-tab="config">配置</button>
          </nav>
          <section id="tab-shots" class="tab-pane active">
            <div class="toolbar">
              <button id="saveShots">保存分镜</button>
              <button id="reloadProject">刷新</button>
            </div>
            <div id="shotsList" class="shot-grid"></div>
          </section>
          <section id="tab-workflow" class="tab-pane">
            <div id="workflowList" class="workflow-grid"></div>
          </section>
          <section id="tab-actions" class="tab-pane">
            <div class="action-grid">
              <button data-action="validate">校验</button>
              <button data-action="jobs-plan">生成计划</button>
              <button data-action="remote-plan">远程预案</button>
              <button data-action="probe">验片</button>
              <button data-action="assemble-plan">合成预案</button>
            </div>
            <pre id="actionOutput" class="output"></pre>
          </section>
          <section id="tab-config" class="tab-pane">
            <div class="toolbar">
              <button id="saveConfig">保存配置</button>
            </div>
            <textarea id="configText" spellcheck="false"></textarea>
          </section>
        </div>
      </section>
    </main>
  </div>
  <script src="/app.js"></script>
</body>
</html>
"""


APP_CSS = """
:root {
  --bg: #f6f7f9;
  --surface: #ffffff;
  --line: #d9dee7;
  --text: #1d2430;
  --muted: #667085;
  --blue: #2563eb;
  --teal: #0f766e;
  --amber: #b45309;
  --red: #b42318;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: var(--text);
  background: var(--bg);
}
button, input, select, textarea { font: inherit; }
button {
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text);
  border-radius: 6px;
  padding: 8px 11px;
  cursor: pointer;
}
button:hover { border-color: #9aa7bd; }
button.primary, .tabs button.active { background: #e8f0ff; border-color: #9bbcff; color: #1746a2; }
input, select, textarea {
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
}
.shell { min-height: 100vh; display: grid; grid-template-rows: auto 1fr; }
.topbar {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}
.brand { font-weight: 700; font-size: 17px; }
.workspace { color: var(--muted); font-size: 12px; margin-top: 2px; }
.create-row { display: flex; gap: 8px; align-items: center; }
.create-row input { width: 180px; padding: 8px 10px; }
.create-row select { min-width: 190px; padding: 8px 10px; }
.layout { display: grid; grid-template-columns: 280px 1fr; min-height: 0; }
.sidebar {
  border-right: 1px solid var(--line);
  background: #fbfcfe;
  padding: 16px 12px;
  overflow: auto;
}
.panel-title, .eyebrow { color: var(--muted); font-size: 11px; font-weight: 700; letter-spacing: 0; text-transform: uppercase; }
.project-list { display: grid; gap: 8px; margin-top: 12px; }
.project-item {
  width: 100%;
  text-align: left;
  padding: 10px;
  border-radius: 7px;
  background: var(--surface);
}
.project-item.active { border-color: #70b8ad; background: #edf8f6; }
.project-item strong { display: block; overflow-wrap: anywhere; }
.project-item span { color: var(--muted); font-size: 12px; }
.main { padding: 18px; overflow: auto; }
.empty {
  height: calc(100vh - 102px);
  display: grid;
  place-items: center;
  color: var(--muted);
  border: 1px dashed var(--line);
  border-radius: 8px;
}
.hidden { display: none; }
.summary-band {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 16px 18px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
}
h1 { margin: 2px 0 0; font-size: 22px; line-height: 1.2; }
.metrics { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.metric { border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; min-width: 94px; background: #fbfcfe; }
.metric b { display: block; font-size: 15px; }
.metric span { color: var(--muted); font-size: 11px; }
.tabs { display: flex; gap: 8px; margin: 14px 0; }
.tab-pane { display: none; }
.tab-pane.active { display: block; }
.toolbar { display: flex; gap: 8px; margin-bottom: 12px; }
.shot-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 12px; }
.shot-card, .workflow-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
}
.shot-head { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; }
.shot-id { color: var(--teal); font-weight: 800; min-width: 38px; }
.field { display: grid; gap: 5px; margin: 8px 0; }
.field label { color: var(--muted); font-size: 12px; }
.field input, .field textarea { width: 100%; padding: 8px; }
.field textarea { min-height: 82px; resize: vertical; }
.small-row { display: grid; grid-template-columns: 1fr 96px; gap: 8px; }
.upload-row { display: flex; align-items: center; gap: 8px; margin-top: 8px; color: var(--muted); font-size: 12px; }
.workflow-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); gap: 12px; }
.workflow-card h3 { margin: 0 0 8px; font-size: 16px; }
.meta-list { display: grid; gap: 5px; color: var(--muted); font-size: 12px; }
.action-grid { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.output {
  margin: 0;
  min-height: 320px;
  background: #101828;
  color: #e4e7ec;
  border-radius: 8px;
  padding: 14px;
  overflow: auto;
  white-space: pre-wrap;
}
#configText {
  width: 100%;
  min-height: 520px;
  padding: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  line-height: 1.45;
}
.status-ok { color: var(--teal); }
.status-warn { color: var(--amber); }
.status-bad { color: var(--red); }
@media (max-width: 900px) {
  .topbar { height: auto; align-items: stretch; flex-direction: column; gap: 12px; padding: 14px; }
  .create-row { flex-wrap: wrap; }
  .layout { grid-template-columns: 1fr; }
  .sidebar { border-right: 0; border-bottom: 1px solid var(--line); max-height: 220px; }
  .summary-band { align-items: flex-start; flex-direction: column; }
}
"""


APP_JS = """
const state = { projects: [], current: null, detail: null, templates: [] };

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.fix ? `${payload.error}\\n${payload.fix}` : payload.error || "Request failed");
  }
  return payload;
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  })[char]);
}

async function loadBoot() {
  const templates = await api("/api/templates");
  state.templates = templates.templates;
  document.getElementById("templateSelect").innerHTML = state.templates
    .map((item) => `<option value="${esc(item.name)}">${esc(item.name)}</option>`)
    .join("");
  const autodl = state.templates.find((item) => item.name === "autodl_comfyui_wan");
  if (autodl) document.getElementById("templateSelect").value = autodl.name;
  await loadProjects();
}

async function loadProjects() {
  const payload = await api("/api/projects");
  state.projects = payload.projects;
  document.getElementById("workspace").textContent = payload.workspace;
  renderProjects();
  if (!state.current && state.projects.length) {
    await selectProject(state.projects[0].name);
  }
}

function renderProjects() {
  const list = document.getElementById("projectList");
  list.innerHTML = state.projects.map((project) => `
    <button class="project-item ${project.name === state.current ? "active" : ""}" data-project="${esc(project.name)}">
      <strong>${esc(project.title || project.name)}</strong>
      <span>${esc(project.shots || 0)} shots · ${esc(project.provider || "unknown")}</span>
    </button>
  `).join("");
  list.querySelectorAll("[data-project]").forEach((button) => {
    button.addEventListener("click", () => selectProject(button.dataset.project));
  });
}

async function selectProject(name) {
  state.current = name;
  renderProjects();
  const payload = await api(`/api/projects/${encodeURIComponent(name)}`);
  state.detail = payload.project;
  document.getElementById("emptyState").classList.add("hidden");
  document.getElementById("projectView").classList.remove("hidden");
  renderProject();
  const config = await api(`/api/projects/${encodeURIComponent(name)}/config`);
  document.getElementById("configText").value = config.text;
}

function renderProject() {
  const project = state.detail;
  document.getElementById("projectTitle").textContent = project.title || project.name;
  document.getElementById("metrics").innerHTML = [
    ["分镜", project.shots],
    ["尺寸", `${project.config.width}x${project.config.height}`],
    ["FPS", project.config.fps],
    ["Workflow", project.workflows],
    ["Remote", project.remote_profiles],
  ].map(([label, value]) => `<div class="metric"><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join("");
  renderShots(project.shots_detail);
  renderWorkflows(project.workflows_detail);
}

function renderShots(shots) {
  document.getElementById("shotsList").innerHTML = shots.map((shot, index) => `
    <article class="shot-card" data-shot-index="${index}">
      <div class="shot-head">
        <div class="shot-id">${esc(shot.id)}</div>
        <input data-field="title" value="${esc(shot.title)}">
      </div>
      <div class="small-row">
        <div class="field"><label>Provider</label><input data-field="provider" value="${esc(shot.provider || "")}"></div>
        <div class="field"><label>Duration</label><input data-field="duration" type="number" min="0.1" step="0.1" value="${esc(shot.duration)}"></div>
      </div>
      <div class="field"><label>Prompt</label><textarea data-field="visual_prompt">${esc(shot.visual_prompt)}</textarea></div>
      <div class="field"><label>Camera</label><input data-field="camera_motion" value="${esc(shot.camera_motion)}"></div>
      <div class="field"><label>Motion</label><input data-field="environment_motion" value="${esc(shot.environment_motion)}"></div>
      <div class="field"><label>Performance</label><input data-field="performance" value="${esc(shot.performance)}"></div>
      <div class="field"><label>Lighting</label><input data-field="lighting" value="${esc(shot.lighting)}"></div>
      <div class="field"><label>Subtitle</label><input data-field="subtitle" value="${esc(shot.subtitle)}"></div>
      <div class="field"><label>Negative</label><textarea data-field="negative_prompt">${esc(shot.negative_prompt)}</textarea></div>
      <div class="upload-row">
        <input type="file" accept="image/png,image/jpeg,image/webp" data-upload="${esc(shot.id)}">
        <span>${esc((shot.refs || [])[0]?.path || "assets/refs")}</span>
      </div>
    </article>
  `).join("");
  document.querySelectorAll("[data-upload]").forEach((input) => {
    input.addEventListener("change", () => uploadFirstFrame(input.dataset.upload, input.files[0]));
  });
}

function collectShots() {
  return [...document.querySelectorAll("[data-shot-index]")].map((card) => {
    const source = state.detail.shots_detail[Number(card.dataset.shotIndex)];
    const shot = structuredClone(source);
    delete shot.manifest;
    card.querySelectorAll("[data-field]").forEach((input) => {
      const key = input.dataset.field;
      shot[key] = key === "duration" ? Number(input.value) : input.value;
    });
    return shot;
  });
}

function renderWorkflows(workflows) {
  document.getElementById("workflowList").innerHTML = workflows.map((workflow) => `
    <article class="workflow-card">
      <h3>${esc(workflow.title)}</h3>
      <div class="meta-list">
        <div>Name: ${esc(workflow.name)}</div>
        <div>Kind: ${esc(workflow.kind)}</div>
        <div>Provider: ${esc(workflow.provider)}</div>
        <div>Path: ${esc(workflow.workflow_path)}</div>
        <div>Tags: ${esc((workflow.tags || []).join(", "))}</div>
      </div>
    </article>
  `).join("");
}

async function uploadFirstFrame(shotId, file) {
  if (!file || !state.current) return;
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
  const payload = await api(`/api/projects/${encodeURIComponent(state.current)}/first-frame`, {
    method: "POST",
    body: JSON.stringify({ shot_id: shotId, filename: file.name, data_url: dataUrl }),
  });
  state.detail = payload.project;
  renderProject();
}

async function runAction(action) {
  const output = document.getElementById("actionOutput");
  output.textContent = "running...";
  const remoteProfile = (state.detail.remote_profiles_detail || [])[0];
  const body = action === "remote-plan"
    ? { profile: remoteProfile && (remoteProfile.name || remoteProfile), provider: "comfyui_wan", kind: "video" }
    : action === "jobs-plan"
      ? { provider: state.detail.config.default_video_provider, kind: "video" }
      : action === "probe"
        ? { dry_run: false }
        : {};
  try {
    const payload = await api(`/api/projects/${encodeURIComponent(state.current)}/${action}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    output.textContent = JSON.stringify(payload.result ?? payload, null, 2);
  } catch (error) {
    output.textContent = String(error.message || error);
  }
}

document.getElementById("createForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = document.getElementById("projectName").value.trim();
  const template = document.getElementById("templateSelect").value;
  if (!name) return;
  await api("/api/projects", { method: "POST", body: JSON.stringify({ name, template }) });
  state.current = name;
  await loadProjects();
  await selectProject(name);
});

document.getElementById("saveShots").addEventListener("click", async () => {
  const payload = await api(`/api/projects/${encodeURIComponent(state.current)}/shots`, {
    method: "PUT",
    body: JSON.stringify({ shots: collectShots() }),
  });
  state.detail = payload.project;
  renderProject();
});

document.getElementById("saveConfig").addEventListener("click", async () => {
  const text = document.getElementById("configText").value;
  const payload = await api(`/api/projects/${encodeURIComponent(state.current)}/config`, {
    method: "PUT",
    body: JSON.stringify({ text }),
  });
  state.detail = payload.project;
  renderProject();
});

document.getElementById("reloadProject").addEventListener("click", () => selectProject(state.current));
document.querySelectorAll(".tabs button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((item) => item.classList.toggle("active", item === button));
    document.querySelectorAll(".tab-pane").forEach((pane) => pane.classList.toggle("active", pane.id === `tab-${button.dataset.tab}`));
  });
});
document.querySelectorAll("[data-action]").forEach((button) => {
  button.addEventListener("click", () => runAction(button.dataset.action));
});

loadBoot().catch((error) => {
  document.getElementById("emptyState").textContent = String(error.message || error);
});
"""
