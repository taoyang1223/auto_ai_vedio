import base64
import json
import threading
from contextlib import contextmanager
from urllib.request import Request, urlopen

from auto_video.project import load_project
from auto_video.web import make_web_server


@contextmanager
def running_web(workspace):
    server = make_web_server(workspace, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def request_json(base_url, path, *, method="GET", payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def request_text(base_url, path):
    with urlopen(f"{base_url}{path}", timeout=5) as response:
        return response.read().decode("utf-8")


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
