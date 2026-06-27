from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import shutil
from argparse import Namespace
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import yaml

from .errors import AutoVideoError, ConfigError
from .comfyui_runtime_doctor import run as run_comfyui_doctor
from .models import PromptProfile
from .pipeline import plan_jobs, submit_jobs
from .probe import probe_project
from .project import load_project, resolve_project_path
from .remote_profiles import build_remote_run_options_from_profile
from .remote_transport import run_remote_worker
from .render import assemble_project
from .templates import init_project, list_templates
from .validation import validate_project
from .web_tasks import TaskLogger, WebTaskQueue
from .workflow_registry import comfyui_wan_adapter_options, list_workflows


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
    "probe": "验片",
    "assemble-plan": "合成预案",
    "assemble": "合成成片",
    "comfyui-check": "检查 ComfyUI 连接",
    "remote-plan": "远程预案",
    "remote-run": "远程执行",
}
PROMPT_PROFILE_KEYS = tuple(PromptProfile.__dataclass_fields__)


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
            if method == "PUT" and tail == ["prompt-profile"]:
                result = _update_prompt_profile(project_root, self._read_json())
                self._send_json({"ok": True, **result, "project": _project_detail(project_root)})
                return
            if method == "POST" and tail == ["first-frame"]:
                result = _upload_first_frame(project_root, self._read_json())
                self._send_json({"ok": True, **result, "project": _project_detail(project_root)})
                return
            if method == "GET" and tail == ["tasks"]:
                self._send_json({"ok": True, "tasks": task_queue.list(project=project_name)})
                return
            if method == "POST" and tail == ["tasks"]:
                task = _enqueue_project_task(task_queue, project_name, project_root, self._read_json())
                self._send_json({"ok": True, "task": task}, status=202)
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
                self._send_json({"ok": True, "tasks": task_queue.list()})
                return
            if method == "GET" and len(parts) == 1:
                task = task_queue.get(parts[0])
                if task is None:
                    raise ConfigError("task not found", fix="Refresh the task list.")
                self._send_json({"ok": True, "task": task})
                return
            if method == "POST" and len(parts) == 2 and parts[1] == "cancel":
                task = task_queue.cancel(parts[0])
                if task is None:
                    raise ConfigError("task not found", fix="Refresh the task list.")
                self._send_json({"ok": True, "task": task})
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
    shots = []
    for shot in project.shots:
        shot_payload = asdict(shot)
        shot_payload["manifest"] = manifest_shots.get(shot.id, {})
        shots.append(shot_payload)
    return {
        **_project_summary(root),
        "config": {
            "aspect_ratio": project.config.aspect_ratio,
            "width": project.config.width,
            "height": project.config.height,
            "fps": project.config.fps,
            "default_video_provider": project.config.default_video_provider,
        },
        "prompt_profile": asdict(project.config.prompt_profile),
        "shots_detail": shots,
        "remote_profiles_detail": _remote_profiles_detail(project),
        "workflows_detail": list_workflows(project),
        "renders": project.manifest.get("renders", {}),
    }


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
    if action == "comfyui-check":
        project = load_project(project_root)
        profile = str(payload.get("profile") or _first_workflow_profile(project))
        logger(f"检查 ComfyUI 工作流：{profile}")
        return _run_comfyui_check(project, profile, payload)
    if action in {"remote-plan", "remote-run"}:
        project = load_project(project_root)
        logger("构建远程执行参数")
        options = build_remote_run_options_from_profile(
            project,
            profile_name=payload.get("profile") or None,
            host=payload.get("host") or None,
            remote_dir=payload.get("remote_dir") or None,
            provider_name=payload.get("provider") or "comfyui_wan",
            kind=str(payload.get("kind") or "video"),
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
        logger("远程预案生成中" if dry_run else "远程任务执行中")
        return run_remote_worker(project, options, dry_run=dry_run)
    raise ConfigError("unsupported task action", fix=f"Use one of: {', '.join(sorted(ACTION_LABELS))}.")


def _first_workflow_profile(project: Any) -> str:
    names = sorted(project.config.comfyui_workflows)
    if not names:
        raise ConfigError("项目没有配置 ComfyUI 工作流", fix="请在项目配置中添加 comfyui_workflows。")
    return names[0]


def _run_comfyui_check(project: Any, profile: str, payload: dict[str, Any]) -> dict[str, Any]:
    options = comfyui_wan_adapter_options(project, profile)
    workflow_path = payload.get("workflow") or options.get("workflow")
    args = Namespace(
        base_url=payload.get("base_url") or options.get("base_url"),
        base_url_env=options.get("base_url_env"),
        workflow=_runtime_workflow_path(project, workflow_path),
        workflow_env=options.get("workflow_env"),
        timeout=float(payload.get("timeout") or 15),
        require_gpu=bool(payload.get("require_gpu", False)),
        require_idle=bool(payload.get("require_idle", False)),
        image_node=options.get("image_node", "224"),
        image_input=options.get("image_input", "image"),
        prompt_node=options.get("prompt_node", "257"),
        prompt_input=options.get("prompt_input", "value"),
        negative_node=options.get("negative_node", "218"),
        negative_input=options.get("negative_input", "text"),
        seed_node=options.get("seed_node", "231"),
        seed_input=options.get("seed_input", "seed"),
        duration_node=options.get("duration_node", "238"),
        duration_input=options.get("duration_input", "value"),
        resolution_node=options.get("resolution_node", "248"),
        resolution_input=options.get("resolution_input", "value"),
        video_node=options.get("video_node", "230"),
        frame_rate_input=options.get("frame_rate_input", "frame_rate"),
        filename_prefix_input=options.get("filename_prefix_input", "filename_prefix"),
        steps_node=options.get("steps_node", ["228", "229"]),
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
