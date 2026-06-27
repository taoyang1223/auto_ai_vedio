import base64
import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from auto_video.project import load_project
from auto_video.templates import init_project
from auto_video.web import make_web_server


@contextmanager
def running_web(workspace, *, token=None):
    server = make_web_server(workspace, host="127.0.0.1", port=0, token=token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def request_json(base_url, path, *, method="GET", payload=None, headers=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def request_json_with_headers(base_url, path, *, method="GET", payload=None, headers=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8")), response.headers


def request_text(base_url, path):
    with urlopen(f"{base_url}{path}", timeout=5) as response:
        return response.read().decode("utf-8")


def request_bytes(base_url, path, *, headers=None):
    request = Request(f"{base_url}{path}", headers=headers or {})
    with urlopen(request, timeout=5) as response:
        return response.read()


def wait_task(base_url, task_id, *, headers=None):
    for _ in range(40):
        payload = request_json(base_url, f"/api/tasks/{task_id}", headers=headers)
        task = payload["task"]
        if task["status"] in {"succeeded", "failed", "canceled"}:
            return task
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} did not finish")


class FakeComfyUIServer:
    def __init__(self):
        self.records = []
        records = self.records

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                records.append(self.path)
                if self.path == "/system_stats":
                    payload = {
                        "system": {"os": "linux"},
                        "devices": [{"name": "NVIDIA GeForce RTX 5090", "type": "cuda", "vram_total": 32607}],
                    }
                elif self.path == "/queue":
                    payload = {"queue_running": [], "queue_pending": []}
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode("utf-8"))

            def log_message(self, format, *args):
                return

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self):
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def write_comfy_workflow(path):
    workflow = {
        "218": {"class_type": "CLIPTextEncode", "inputs": {"text": "negative"}},
        "224": {"class_type": "LoadImage", "inputs": {"image": "input.png"}},
        "228": {"class_type": "KSamplerAdvanced", "inputs": {"steps": 4, "cfg": 1.0}},
        "229": {"class_type": "KSamplerAdvanced", "inputs": {"steps": 4, "cfg": 1.0}},
        "230": {"class_type": "VHS_VideoCombine", "inputs": {"frame_rate": 16, "filename_prefix": "demo"}},
        "231": {"class_type": "Seed", "inputs": {"seed": 42}},
        "238": {"class_type": "INTConstant", "inputs": {"value": 2}},
        "248": {"class_type": "INTConstant", "inputs": {"value": 832}},
        "257": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "prompt"}},
    }
    path.write_text(json.dumps(workflow, ensure_ascii=False), encoding="utf-8")


def append_comfy_workflow(project_root, *, base_url, workflow_path):
    with (project_root / "project.yaml").open("a", encoding="utf-8") as handle:
        handle.write(
            f"""
comfyui_workflows:
  local_i2v:
    title: Local I2V
    provider: comfyui_wan
    kind: image_to_video
    base_url: {base_url}
    workflow_path: {workflow_path.as_posix()}
"""
        )


def test_web_serves_app_shell(tmp_path):
    with running_web(tmp_path) as base_url:
        html = request_text(base_url, "/")
        css = request_text(base_url, "/app.css")
        js = request_text(base_url, "/app.js")

    assert "Auto AI Video" in html
    assert ".summary-band" in css
    assert "loadBoot" in js


def test_web_api_creates_project_and_plans_jobs(tmp_path):
    with running_web(tmp_path) as base_url:
        created = request_json(
            base_url,
            "/api/projects",
            method="POST",
            payload={"name": "wan_story", "template": "autodl_comfyui_wan"},
        )
        listed = request_json(base_url, "/api/projects")
        detail = request_json(base_url, "/api/projects/wan_story")
        validated = request_json(base_url, "/api/projects/wan_story/validate", method="POST", payload={})
        planned = request_json(
            base_url,
            "/api/projects/wan_story/jobs-plan",
            method="POST",
            payload={"provider": "comfyui_wan", "kind": "video"},
        )

    assert created["ok"] is True
    assert listed["projects"][0]["name"] == "wan_story"
    assert detail["project"]["workflows_detail"][0]["name"] == "wan2_2_smoothmix_i2v"
    assert validated["ok"] is True
    assert planned["result"]["planned"][0]["provider"] == "comfyui_wan"


def test_web_api_deletes_project(tmp_path):
    with running_web(tmp_path) as base_url:
        request_json(
            base_url,
            "/api/projects",
            method="POST",
            payload={"name": "delete_me", "template": "demo"},
        )
        deleted = request_json(base_url, "/api/projects/delete_me", method="DELETE")
        listed = request_json(base_url, "/api/projects")

    assert deleted["deleted"] == "delete_me"
    assert listed["projects"] == []
    assert not (tmp_path / "delete_me").exists()


def test_web_missing_project_returns_chinese_error(tmp_path):
    with running_web(tmp_path) as base_url:
        try:
            request_json(base_url, "/api/projects/missing")
        except HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("missing project should fail")

    assert body["error"] == "项目不存在或配置缺失"
    assert body["fix"] == "请从左侧选择现有项目，或重新新建项目。"


def test_web_checks_comfyui_workflow(tmp_path):
    project_root = tmp_path / "demo"
    workflow = tmp_path / "workflow.json"
    init_project(project_root, template_name="demo")
    write_comfy_workflow(workflow)

    with FakeComfyUIServer() as comfyui:
        append_comfy_workflow(project_root, base_url=comfyui.url, workflow_path=workflow)
        with running_web(tmp_path) as base_url:
            payload = request_json(
                base_url,
                "/api/projects/demo/workflow-check",
                method="POST",
                payload={"profile": "local_i2v", "require_gpu": True, "require_idle": True},
            )

    result = payload["result"]
    assert result["ok"] is True
    assert result["profile"] == "local_i2v"
    assert result["base_url"] == comfyui.url
    assert result["workflow"] == workflow.as_posix()
    assert comfyui.records == ["/system_stats", "/queue"]


def test_web_api_saves_shots_and_uploads_first_frame(tmp_path):
    with running_web(tmp_path) as base_url:
        request_json(
            base_url,
            "/api/projects",
            method="POST",
            payload={"name": "demo", "template": "demo"},
        )
        detail = request_json(base_url, "/api/projects/demo")["project"]
        shots = detail["shots_detail"]
        shots[0]["visual_prompt"] = "updated web prompt"
        request_json(base_url, "/api/projects/demo/shots", method="PUT", payload={"shots": shots})
        image_body = base64.b64encode(b"not-a-real-png-but-good-enough-for-validation").decode("ascii")
        uploaded = request_json(
            base_url,
            "/api/projects/demo/first-frame",
            method="POST",
            payload={"shot_id": "S01", "filename": "frame.png", "data_base64": image_body},
        )

    project = load_project(tmp_path / "demo")
    assert project.shots[0].visual_prompt == "updated web prompt"
    assert project.shots[0].refs[0].path == "assets/refs/S01_first_frame.png"
    assert uploaded["bytes"] > 0


def test_web_serves_project_media(tmp_path):
    with running_web(tmp_path) as base_url:
        request_json(
            base_url,
            "/api/projects",
            method="POST",
            payload={"name": "demo", "template": "demo"},
        )
        image_body = base64.b64encode(b"preview-image").decode("ascii")
        request_json(
            base_url,
            "/api/projects/demo/first-frame",
            method="POST",
            payload={"shot_id": "S01", "filename": "frame.png", "data_base64": image_body},
        )
        body = request_bytes(base_url, "/media/demo/assets/refs/S01_first_frame.png")

    assert body == b"preview-image"


def test_web_auth_protects_api_and_media(tmp_path):
    with running_web(tmp_path, token="secret-token") as base_url:
        status = request_json(base_url, "/api/auth/status")
        assert status["enabled"] is True
        assert status["authenticated"] is False

        try:
            request_json(base_url, "/api/projects")
        except HTTPError as exc:
            assert exc.code == 401
        else:
            raise AssertionError("unauthenticated API request should fail")

        try:
            request_json(base_url, "/api/auth/login", method="POST", payload={"token": "wrong"})
        except HTTPError as exc:
            assert exc.code == 401
        else:
            raise AssertionError("wrong token should fail")

        login_payload, login_headers = request_json_with_headers(
            base_url,
            "/api/auth/login",
            method="POST",
            payload={"token": "secret-token"},
        )
        cookie = login_headers["Set-Cookie"].split(";", 1)[0]
        request_json(
            base_url,
            "/api/projects",
            method="POST",
            payload={"name": "demo", "template": "demo"},
            headers={"Cookie": cookie},
        )
        image_body = base64.b64encode(b"protected-preview").decode("ascii")
        request_json(
            base_url,
            "/api/projects/demo/first-frame",
            method="POST",
            payload={"shot_id": "S01", "filename": "frame.png", "data_base64": image_body},
            headers={"Cookie": cookie},
        )
        try:
            request_bytes(base_url, "/media/demo/assets/refs/S01_first_frame.png")
        except HTTPError as exc:
            assert exc.code == 401
        else:
            raise AssertionError("unauthenticated media request should fail")

        listed = request_json(base_url, "/api/projects", headers={"Cookie": cookie})
        bearer = request_json(base_url, "/api/projects", headers={"Authorization": "Bearer secret-token"})
        media_body = request_bytes(base_url, "/media/demo/assets/refs/S01_first_frame.png", headers={"Cookie": cookie})

    assert login_payload["authenticated"] is True
    assert listed["ok"] is True
    assert bearer["ok"] is True
    assert media_body == b"protected-preview"


def test_web_task_queue_runs_project_actions(tmp_path):
    with running_web(tmp_path) as base_url:
        request_json(
            base_url,
            "/api/projects",
            method="POST",
            payload={"name": "demo", "template": "demo"},
        )
        queued = request_json(
            base_url,
            "/api/projects/demo/tasks",
            method="POST",
            payload={"action": "validate"},
        )["task"]
        validate_task = wait_task(base_url, queued["id"])

        planned = request_json(
            base_url,
            "/api/projects/demo/tasks",
            method="POST",
            payload={"action": "jobs-plan", "payload": {"provider": "mock", "kind": "video"}},
        )["task"]
        plan_task = wait_task(base_url, planned["id"])
        project_tasks = request_json(base_url, "/api/projects/demo/tasks")["tasks"]
        global_tasks = request_json(base_url, "/api/tasks")["tasks"]

    assert queued["status"] == "queued"
    assert validate_task["status"] == "succeeded"
    assert validate_task["result"]["warning_count"] == 0
    assert plan_task["status"] == "succeeded"
    assert plan_task["result"]["planned"][0]["provider"] == "mock"
    assert [task["id"] for task in project_tasks][:2] == [planned["id"], queued["id"]]
    assert global_tasks[0]["project"] == "demo"
