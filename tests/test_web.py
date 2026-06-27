import base64
import json
import os
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


def write_comfy_image_workflow(path):
    workflow = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 4, "cfg": 1}},
        "118": {"class_type": "CR SDXL Aspect Ratio", "inputs": {"width": 512, "height": 512}},
        "187": {"class_type": "CLIPTextEncode", "inputs": {"text": "prompt"}},
        "437": {"class_type": "CLIPTextEncode", "inputs": {"text": "negative"}},
        "499": {"class_type": "SaveImage", "inputs": {"filename_prefix": "demo"}},
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


def append_comfy_image_workflow(project_root, *, base_url, workflow_path):
    with (project_root / "project.yaml").open("a", encoding="utf-8") as handle:
        handle.write(
            f"""
comfyui_workflows:
  local_t2i:
    title: Local T2I
    provider: comfyui_image
    kind: text_to_image
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
    workflow_names = {workflow["name"] for workflow in detail["project"]["workflows_detail"]}
    assert {"qwen2512_first_frame", "wan2_2_smoothmix_i2v"}.issubset(workflow_names)
    workflow_titles = {workflow["title"] for workflow in detail["project"]["workflows_detail"]}
    assert "Qwen2512 首帧文生图" in workflow_titles
    assert "Wan2.2 SmoothMix 图生视频" in workflow_titles
    shot_titles = [shot["title"] for shot in detail["project"]["shots_detail"]]
    assert shot_titles == ["建立主角", "流程运转", "成片揭示"]
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


def test_web_marks_generated_shot_stale_when_first_frame_is_newer(tmp_path):
    with running_web(tmp_path) as base_url:
        request_json(
            base_url,
            "/api/projects",
            method="POST",
            payload={"name": "wan_story", "template": "autodl_comfyui_wan"},
        )
        project = tmp_path / "wan_story"
        output = project / "generated" / "clips" / "S01.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("old video", encoding="utf-8")
        ref = project / "assets" / "refs" / "S01_first_frame.png"
        os.utime(output, (1000, 1000))
        os.utime(ref, (2000, 2000))
        (project / "manifest.json").write_text(
            json.dumps(
                {
                    "project": "wan_story",
                    "schema_version": "0.1",
                    "assets": {},
                    "shots": {"S01": {"status": "generated", "provider": "comfyui_wan", "clip": "generated/clips/S01.mp4"}},
                    "renders": {},
                    "jobs": {"wan_story:S01:video:comfyui_wan": {"status": "succeeded"}},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        detail = request_json(base_url, "/api/projects/wan_story")["project"]

    assert detail["shots_detail"][0]["freshness"]["status"] == "stale"


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


def test_web_checks_comfyui_image_workflow(tmp_path):
    project_root = tmp_path / "demo"
    workflow = tmp_path / "image-workflow.json"
    init_project(project_root, template_name="demo")
    write_comfy_image_workflow(workflow)

    with FakeComfyUIServer() as comfyui:
        append_comfy_image_workflow(project_root, base_url=comfyui.url, workflow_path=workflow)
        with running_web(tmp_path) as base_url:
            payload = request_json(
                base_url,
                "/api/projects/demo/workflow-check",
                method="POST",
                payload={"profile": "local_t2i", "kind": "text_to_image", "require_gpu": True},
            )

    result = payload["result"]
    assert result["ok"] is True
    workflow_check = next(check for check in result["checks"] if check["name"] == "workflow")
    assert workflow_check["details"]["required"]["width"] == ["118", "width"]


def test_web_updates_comfyui_workflow_settings(tmp_path):
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

    with running_web(tmp_path) as base_url:
        request_json(
            base_url,
            "/api/projects",
            method="POST",
            payload={"name": "wan_story", "template": "autodl_comfyui_wan"},
        )
        payload = request_json(
            base_url,
            "/api/projects/wan_story/workflows/wan2_2_smoothmix_i2v",
            method="PUT",
            payload={
                "base_url": "http://127.0.0.1:7000/",
                "workflow_json": json.dumps(workflow),
                "workflow_filename": "wan api.json",
            },
        )

    project = load_project(tmp_path / "wan_story")
    workflow_config = project.config.comfyui_workflows["wan2_2_smoothmix_i2v"]
    provider_env = project.config.providers["comfyui_wan"].options["env"]
    remote_env = project.config.remote_profiles["autodl_5090"]["remote_env"]

    saved_workflow = next(
        workflow for workflow in payload["project"]["workflows_detail"] if workflow["name"] == "wan2_2_smoothmix_i2v"
    )
    assert saved_workflow["base_url"] == "http://127.0.0.1:7000"
    assert workflow_config["workflow_path"] == "workflows/wan_api.json"
    assert (tmp_path / "wan_story" / "workflows" / "wan_api.json").exists()
    assert provider_env["COMFYUI_BASE_URL"] == "http://127.0.0.1:7000"
    assert provider_env["COMFYUI_WORKFLOW"] == "workflows/wan_api.json"
    assert remote_env["COMFYUI_WORKFLOW"] == "workflows/wan_api.json"


def test_web_api_updates_remote_profile_and_plans_remote_run(tmp_path):
    with running_web(tmp_path) as base_url:
        request_json(
            base_url,
            "/api/projects",
            method="POST",
            payload={"name": "wan_story", "template": "autodl_comfyui_wan"},
        )
        payload = request_json(
            base_url,
            "/api/projects/wan_story/remote-profiles/autodl_5090",
            method="PUT",
            payload={
                "host": "root@connect.westd.seetacloud.com",
                "ssh_port": "13159",
                "remote_dir": "/root/auto-video/jobs/wan_story",
                "local_dir": "/tmp/auto-video-wan_story",
                "remote_auto_video": "/opt/auto-ai-video/.venv/bin/auto-video",
            },
        )
        task_payload = request_json(
            base_url,
            "/api/projects/wan_story/tasks",
            method="POST",
            payload={
                "action": "remote-plan",
                "payload": {"profile": "autodl_5090", "provider": "comfyui_wan", "kind": "video"},
            },
        )
        task = wait_task(base_url, task_payload["task"]["id"])

    project = load_project(tmp_path / "wan_story")
    remote_profile = project.config.remote_profiles["autodl_5090"]
    detail_profile = payload["project"]["remote_profiles_detail"][0]

    assert detail_profile["host"] == "root@connect.westd.seetacloud.com"
    assert detail_profile["ssh_port"] == "13159"
    assert remote_profile["host"] == "root@connect.westd.seetacloud.com"
    assert remote_profile["remote_dir"] == "/root/auto-video/jobs/wan_story"
    assert remote_profile["local_dir"] == "/tmp/auto-video-wan_story"
    assert remote_profile["remote_auto_video"] == "/opt/auto-ai-video/.venv/bin/auto-video"
    assert remote_profile["ssh_options"] == ["Port=13159"]
    assert task["status"] == "succeeded"
    assert task["result"]["dry_run"] is True
    assert task["result"]["host"] == "root@connect.westd.seetacloud.com"
    assert "Port=13159" in task["result"]["commands"]["run"]


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


def test_web_api_updates_prompt_profile(tmp_path):
    with running_web(tmp_path) as base_url:
        request_json(
            base_url,
            "/api/projects",
            method="POST",
            payload={"name": "wan_story", "template": "autodl_comfyui_wan"},
        )
        payload = request_json(
            base_url,
            "/api/projects/wan_story/prompt-profile",
            method="PUT",
            payload={
                "subject": "同一位 AI 影像创作者",
                "character": "保持同一张脸和同一套服装",
                "setting": "现代影像工作室",
                "visual_style": "premium cinematic commercial",
                "camera_style": "smooth controlled dolly",
                "motion_style": "natural hand movement",
                "lighting_style": "soft screen glow",
                "continuity": "preserve subject identity across shots",
                "negative": "identity drift, style drift",
            },
        )

    project = load_project(tmp_path / "wan_story")
    assert payload["project"]["prompt_profile"]["subject"] == "同一位 AI 影像创作者"
    assert project.config.prompt_profile.character == "保持同一张脸和同一套服装"
    assert project.config.prompt_profile.negative == "identity drift, style drift"


def test_web_api_manages_first_frame_prompts(tmp_path):
    with running_web(tmp_path) as base_url:
        request_json(
            base_url,
            "/api/projects",
            method="POST",
            payload={"name": "demo", "template": "demo"},
        )
        drafted = request_json(base_url, "/api/projects/demo/first-frame-prompts")
        saved = request_json(
            base_url,
            "/api/projects/demo/first-frame-prompts",
            method="PUT",
            payload={
                "prompts": [
                    {
                        "shot_id": "S01",
                        "prompt": "custom first frame prompt",
                        "negative_prompt": "text, watermark",
                    }
                ]
            },
        )
        reloaded = request_json(base_url, "/api/projects/demo/first-frame-prompts")

    prompt_file = tmp_path / "demo" / "assets" / "first_frame_prompts.json"
    prompt_payload = json.loads(prompt_file.read_text(encoding="utf-8"))

    assert drafted["prompts"][0]["shot_id"] == "S01"
    assert "First-frame key visual" in drafted["prompts"][0]["prompt"]
    assert saved["prompts"][0]["prompt"] == "custom first frame prompt"
    assert saved["prompts"][0]["saved"] is True
    assert reloaded["prompts"][0]["negative_prompt"] == "text, watermark"
    assert prompt_payload["prompts"][0]["shot_id"] == "S01"


def test_web_task_generates_first_frames_and_updates_project_refs(tmp_path):
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
            payload={
                "action": "first-frame-generate",
                "payload": {"provider": "mock", "only": ["S01"]},
            },
        )["task"]
        task = wait_task(base_url, queued["id"])
        detail = request_json(base_url, "/api/projects/demo")["project"]

    image_path = tmp_path / "demo" / "assets" / "refs" / "S01_first_frame.png"

    assert task["status"] == "succeeded"
    assert task["result"]["first_frames"]["count"] == 1
    assert detail["shots_detail"][0]["refs"][0]["path"] == "assets/refs/S01_first_frame.png"
    assert image_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_web_api_drafts_and_applies_script_storyboard(tmp_path):
    with running_web(tmp_path) as base_url:
        request_json(
            base_url,
            "/api/projects",
            method="POST",
            payload={"name": "wan_story", "template": "autodl_comfyui_wan"},
        )
        manifest_path = tmp_path / "wan_story" / "manifest.json"
        manifest_path.write_text(
            json.dumps({"shots": {"S01": {"clip": "generated/clips/S01.mp4"}}, "renders": {"final": {"path": "renders/final.mp4"}}}),
            encoding="utf-8",
        )
        drafted = request_json(
            base_url,
            "/api/projects/wan_story/script-draft",
            method="POST",
            payload={
                "script": "创作者把一句想法写在故事板上。镜头展示自动化生产过程。最终视频在屏幕上播放。",
                "shot_count": 3,
                "duration": 4,
            },
        )
        applied = request_json(
            base_url,
            "/api/projects/wan_story/script-apply",
            method="POST",
            payload={"shots": drafted["shots"]},
        )

    project = load_project(tmp_path / "wan_story")
    manifest = json.loads((tmp_path / "wan_story" / "manifest.json").read_text(encoding="utf-8"))

    assert len(drafted["shots"]) == 3
    assert drafted["shots"][0]["title"].startswith("开场建立")
    assert applied["applied"] == 3
    assert project.shots[0].visual_prompt == drafted["shots"][0]["visual_prompt"]
    assert manifest["shots"] == {}
    assert manifest["renders"] == {}


def test_web_api_manages_asset_library_and_shot_refs(tmp_path):
    with running_web(tmp_path) as base_url:
        request_json(
            base_url,
            "/api/projects",
            method="POST",
            payload={"name": "demo", "template": "demo"},
        )
        uploaded = request_json(
            base_url,
            "/api/projects/demo/assets",
            method="POST",
            payload={
                "label": "主角参考",
                "type": "image",
                "role": "style_reference",
                "usage": "preserve_subject",
                "filename": "hero.png",
                "data_base64": base64.b64encode(b"fake-image").decode("ascii"),
            },
        )
        asset = uploaded["asset"]
        listed = request_json(base_url, "/api/projects/demo/assets")
        bound = request_json(
            base_url,
            "/api/projects/demo/shot-refs",
            method="PUT",
            payload={
                "shot_id": "S01",
                "refs": [
                    {
                        "path": asset["path"],
                        "type": asset["type"],
                        "role": asset["role"],
                        "usage": asset["usage"],
                    }
                ],
            },
        )
        deleted = request_json(base_url, f"/api/projects/demo/assets/{asset['id']}", method="DELETE")

    project = load_project(tmp_path / "demo")
    asset_file = tmp_path / "demo" / asset["path"]

    assert listed["assets"]
    assert bound["project"]["shots_detail"][0]["refs"][0]["path"] == asset["path"]
    assert bound["assets"][0]["bound_shots"] or any("S01" in item["bound_shots"] for item in bound["assets"])
    assert deleted["deleted"] == asset["id"]
    assert project.shots[0].refs == ()
    assert not asset_file.exists()


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


def test_web_task_one_click_production_runs_mock_pipeline(tmp_path):
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
            payload={"action": "produce-all", "payload": {"local_only": True}},
        )["task"]
        task = wait_task(base_url, queued["id"])

    steps = [step["step"] for step in task["result"]["steps"]]
    assert task["status"] == "succeeded"
    assert steps == ["validate", "first_frames", "videos", "voiceover", "probe", "assemble", "continuity"]
    assert task["result"]["steps"][2]["result"]["count"] == 1
    assert task["result"]["steps"][4]["result"]["dry_run"] is True


def test_web_task_extracts_continuity_tail_frames_dry_run(tmp_path):
    with running_web(tmp_path) as base_url:
        request_json(
            base_url,
            "/api/projects",
            method="POST",
            payload={"name": "wan_story", "template": "autodl_comfyui_wan"},
        )
        project = tmp_path / "wan_story"
        clip = project / "generated" / "clips" / "S01.mp4"
        clip.parent.mkdir(parents=True, exist_ok=True)
        clip.write_bytes(b"fake-video")
        (project / "manifest.json").write_text(
            json.dumps(
                {
                    "project": "wan_story",
                    "schema_version": "0.1",
                    "assets": {},
                    "shots": {"S01": {"status": "generated", "clip": "generated/clips/S01.mp4"}},
                    "renders": {},
                    "jobs": {},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        queued = request_json(
            base_url,
            "/api/projects/wan_story/tasks",
            method="POST",
            payload={"action": "continuity", "payload": {"dry_run": True}},
        )["task"]
        task = wait_task(base_url, queued["id"])

    assert task["status"] == "succeeded"
    assert task["result"]["planned"][0]["shot_id"] == "S01"
    assert task["result"]["planned"][0]["next_shot_id"] == "S02"


def test_web_task_remote_wrapup_dry_run_uses_profile(tmp_path):
    with running_web(tmp_path) as base_url:
        request_json(
            base_url,
            "/api/projects",
            method="POST",
            payload={"name": "wan_story", "template": "autodl_comfyui_wan"},
        )
        request_json(
            base_url,
            "/api/projects/wan_story/remote-profiles/autodl_5090",
            method="PUT",
            payload={
                "host": "root@example.com",
                "ssh_port": "2222",
                "remote_dir": "/root/auto-video/jobs/wan_story",
                "local_dir": "/tmp/auto-video-wan_story",
            },
        )
        queued = request_json(
            base_url,
            "/api/projects/wan_story/tasks",
            method="POST",
            payload={"action": "remote-wrapup", "payload": {"profile": "autodl_5090", "dry_run": True}},
        )["task"]
        task = wait_task(base_url, queued["id"])

    assert task["status"] == "succeeded"
    assert task["result"]["dry_run"] is True
    assert task["result"]["host"] == "root@example.com"
    assert task["result"]["checks"][0]["status"] == "planned"
