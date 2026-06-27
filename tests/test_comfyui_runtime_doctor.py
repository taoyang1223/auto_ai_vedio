import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCTOR = ROOT / "scripts" / "comfyui_runtime_doctor.py"


class FakeComfyUIServer:
    def __init__(
        self,
        *,
        system_stats: dict | None = None,
        queue: dict | None = None,
        status: int = 200,
    ):
        self.records: list[dict] = []
        records = self.records
        response_status = status
        stats_payload = system_stats or {
            "system": {"os": "linux"},
            "devices": [{"name": "NVIDIA GeForce RTX 5090", "type": "cuda", "vram_total": 32607}],
        }
        queue_payload = queue or {"queue_running": [], "queue_pending": []}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                records.append({"path": self.path, "headers": dict(self.headers)})
                self.send_response(response_status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                if self.path == "/system_stats":
                    self.wfile.write(json.dumps(stats_payload).encode("utf-8"))
                elif self.path == "/queue":
                    self.wfile.write(json.dumps(queue_payload).encode("utf-8"))
                else:
                    self.wfile.write(json.dumps({"error": "not found"}).encode("utf-8"))

            def log_message(self, format, *args):
                return

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _workflow(tmp_path: Path, *, missing_node: str | None = None) -> Path:
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
    if missing_node:
        workflow.pop(missing_node)
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _image_workflow(tmp_path: Path, *, missing_node: str | None = None) -> Path:
    workflow = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 4, "cfg": 1}},
        "118": {"class_type": "CR SDXL Aspect Ratio", "inputs": {"width": 512, "height": 512}},
        "187": {"class_type": "CLIPTextEncode", "inputs": {"text": "prompt"}},
        "437": {"class_type": "CLIPTextEncode", "inputs": {"text": "negative"}},
        "499": {"class_type": "SaveImage", "inputs": {"filename_prefix": "demo"}},
    }
    if missing_node:
        workflow.pop(missing_node)
    path = tmp_path / "image-workflow.json"
    path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _run_doctor(args: list[str], *, env: dict[str, str] | None = None):
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, DOCTOR.as_posix(), *args],
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )


def _run_doctor_module(args: list[str], *, env: dict[str, str] | None = None):
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "auto_video.comfyui_runtime_doctor", *args],
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )


def test_comfyui_runtime_doctor_healthy_workflow_exits_zero(tmp_path: Path):
    workflow = _workflow(tmp_path)
    with FakeComfyUIServer() as server:
        completed = _run_doctor(
            [
                "--base-url",
                server.url,
                "--workflow",
                workflow.as_posix(),
                "--require-gpu",
                "--require-idle",
            ]
        )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["base_url"] == server.url
    assert payload["workflow"] == workflow.as_posix()
    assert [record["path"] for record in server.records] == ["/system_stats", "/queue"]
    assert [check["status"] for check in payload["checks"]] == ["ok", "ok", "ok", "ok", "ok", "ok", "ok"]
    workflow_check = next(check for check in payload["checks"] if check["name"] == "workflow")
    assert workflow_check["details"]["node_count"] == 9


def test_comfyui_runtime_doctor_module_reads_env(tmp_path: Path):
    workflow = _workflow(tmp_path)
    with FakeComfyUIServer() as server:
        completed = _run_doctor_module(
            ["--base-url-env", "COMFYUI_BASE_URL", "--workflow-env", "COMFYUI_WORKFLOW"],
            env={"COMFYUI_BASE_URL": server.url, "COMFYUI_WORKFLOW": workflow.as_posix()},
        )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["base_url"] == server.url
    assert payload["workflow"] == workflow.as_posix()


def test_comfyui_runtime_doctor_image_mode_checks_text_to_image_nodes(tmp_path: Path):
    workflow = _image_workflow(tmp_path)
    with FakeComfyUIServer() as server:
        completed = _run_doctor(
            [
                "--mode",
                "image",
                "--base-url",
                server.url,
                "--workflow",
                workflow.as_posix(),
                "--require-gpu",
            ]
        )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    workflow_check = next(check for check in payload["checks"] if check["name"] == "workflow")
    assert workflow_check["status"] == "ok"
    assert workflow_check["details"]["required"]["width"] == ["118", "width"]


def test_comfyui_runtime_doctor_missing_workflow_node_exits_one(tmp_path: Path):
    workflow = _workflow(tmp_path, missing_node="224")
    with FakeComfyUIServer() as server:
        completed = _run_doctor(["--base-url", server.url, "--workflow", workflow.as_posix()])

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    workflow_check = next(check for check in payload["checks"] if check["name"] == "workflow")
    assert workflow_check["status"] == "failed"
    assert "image: node 224" in workflow_check["details"]["missing"]


def test_comfyui_runtime_doctor_require_idle_fails_when_queue_busy(tmp_path: Path):
    workflow = _workflow(tmp_path)
    with FakeComfyUIServer(queue={"queue_running": [["running-job"]], "queue_pending": []}) as server:
        completed = _run_doctor(
            ["--base-url", server.url, "--workflow", workflow.as_posix(), "--require-idle"]
        )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    queue_idle = next(check for check in payload["checks"] if check["name"] == "queue_idle")
    assert queue_idle["status"] == "failed"
    assert queue_idle["details"]["running"] == 1


def test_comfyui_runtime_doctor_missing_base_url_env_exits_one(tmp_path: Path):
    workflow = _workflow(tmp_path)
    completed = _run_doctor(
        ["--base-url-env", "COMFYUI_BASE_URL_MISSING", "--workflow", workflow.as_posix()],
        env={"COMFYUI_BASE_URL_MISSING": ""},
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["ok"] is False
    assert payload["checks"][0]["name"] == "base_url"
    assert payload["checks"][0]["status"] == "failed"
    assert "COMFYUI_BASE_URL_MISSING" in payload["checks"][0]["message"]
