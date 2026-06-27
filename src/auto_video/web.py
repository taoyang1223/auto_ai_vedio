from __future__ import annotations

import base64
import json
import re
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .errors import AutoVideoError, ConfigError
from .pipeline import plan_jobs
from .probe import probe_project
from .project import load_project
from .remote_profiles import build_remote_run_options_from_profile, list_remote_profiles
from .remote_transport import run_remote_worker
from .render import assemble_project
from .templates import init_project, list_templates
from .validation import validate_project
from .workflow_registry import list_workflows


PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def run_web_server(workspace: Path, *, host: str = "127.0.0.1", port: int = 8765) -> None:
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    server = make_web_server(workspace, host=host, port=port)
    print(f"auto-video web listening on http://{host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def make_web_server(workspace: Path, *, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    handler = _handler_factory(workspace)
    return ThreadingHTTPServer((host, port), handler)


def _handler_factory(workspace: Path):
    class AutoVideoWebHandler(BaseHTTPRequestHandler):
        server_version = "AutoVideoWeb/0.1"

        def do_GET(self) -> None:
            self._handle("GET")

        def do_POST(self) -> None:
            self._handle("POST")

        def do_PUT(self) -> None:
            self._handle("PUT")

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _handle(self, method: str) -> None:
            try:
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/") or "/"
                parts = [unquote(part) for part in path.split("/") if part]
                if method == "GET" and path == "/":
                    self._send_html(APP_HTML)
                    return
                if method == "GET" and path == "/app.css":
                    self._send_text(APP_CSS, "text/css; charset=utf-8")
                    return
                if method == "GET" and path == "/app.js":
                    self._send_text(APP_JS, "application/javascript; charset=utf-8")
                    return
                if parts[:1] != ["api"]:
                    raise ConfigError("unknown route", fix="Use the web console API routes.")
                self._handle_api(method, parts[1:])
            except AutoVideoError as exc:
                self._send_json({"ok": False, "error": exc.message, "fix": exc.fix}, status=400)
            except json.JSONDecodeError as exc:
                self._send_json({"ok": False, "error": "invalid JSON", "fix": str(exc)}, status=400)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc), "fix": "Check the request and server log."}, status=500)

        def _handle_api(self, method: str, parts: list[str]) -> None:
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
            if method == "POST" and tail == ["first-frame"]:
                result = _upload_first_frame(project_root, self._read_json())
                self._send_json({"ok": True, **result, "project": _project_detail(project_root)})
                return
            if method == "POST" and tail == ["validate"]:
                project = load_project(project_root)
                warnings = validate_project(project)
                self._send_json({"ok": True, "warnings": warnings})
                return
            if method == "POST" and tail == ["jobs-plan"]:
                payload = self._read_json()
                project = load_project(project_root)
                result = plan_jobs(
                    project,
                    kind=str(payload.get("kind") or "video"),
                    provider_name=payload.get("provider") or None,
                    failed_only=bool(payload.get("failed_only", False)),
                    skip_succeeded=bool(payload.get("skip_succeeded", False)),
                )
                self._send_json({"ok": True, "result": result})
                return
            if method == "POST" and tail == ["probe"]:
                payload = self._read_json()
                result = probe_project(
                    load_project(project_root),
                    dry_run=bool(payload.get("dry_run", False)),
                    blackdetect=bool(payload.get("blackdetect", False)),
                )
                self._send_json({"ok": True, "result": result})
                return
            if method == "POST" and tail == ["assemble-plan"]:
                result = assemble_project(load_project(project_root), dry_run=True)
                self._send_json({"ok": True, "result": result})
                return
            if method == "POST" and tail == ["remote-plan"]:
                payload = self._read_json()
                project = load_project(project_root)
                options = build_remote_run_options_from_profile(
                    project,
                    profile_name=payload.get("profile") or None,
                    host=None,
                    remote_dir=None,
                    provider_name=payload.get("provider") or "comfyui_wan",
                    kind=str(payload.get("kind") or "video"),
                    only=None,
                    failed_only=bool(payload.get("failed_only", False)),
                    skip_succeeded=bool(payload.get("skip_succeeded", False)),
                    local_dir=None,
                    remote_auto_video=None,
                    ssh_options=(),
                    rsync_options=(),
                    remote_env=(),
                )
                result = run_remote_worker(project, options, dry_run=True)
                self._send_json({"ok": True, "result": result})
                return
            raise ConfigError("unknown project API route", fix="Refresh the web console and retry.")

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

    return AutoVideoWebHandler


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
        "shots_detail": shots,
        "remote_profiles_detail": list_remote_profiles(project),
        "workflows_detail": list_workflows(project),
        "renders": project.manifest.get("renders", {}),
    }


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
  const body = action === "remote-plan"
    ? { profile: (state.detail.remote_profiles_detail || [])[0], provider: "comfyui_wan", kind: "video" }
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
