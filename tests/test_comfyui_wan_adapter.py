import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from auto_video.pipeline import submit_jobs
from auto_video.project import load_project

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "comfyui_wan_adapter.py"


class FakeComfyUIServer:
    def __init__(self, *, media_body: bytes = b"comfy-mp4", history_empty_count: int = 0):
        self.records: list[dict] = []
        records = self.records
        response_media_body = media_body
        empty_count = {"remaining": history_empty_count}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                records.append(
                    {
                        "method": "POST",
                        "path": self.path,
                        "headers": dict(self.headers),
                        "body": raw_body,
                    }
                )
                if self.path == "/upload/image":
                    self._json({"name": "uploaded-first-frame.png", "subfolder": "", "type": "input"})
                    return
                if self.path == "/prompt":
                    self._json({"prompt_id": "prompt-123"})
                    return
                self.send_error(404)

            def do_GET(self):
                records.append({"method": "GET", "path": self.path, "headers": dict(self.headers)})
                parsed = urlparse(self.path)
                if parsed.path == "/history/prompt-123":
                    if empty_count["remaining"] > 0:
                        empty_count["remaining"] -= 1
                        self._json({})
                        return
                    self._json(
                        {
                            "prompt-123": {
                                "outputs": {
                                    "230": {
                                        "gifs": [
                                            {
                                                "filename": "auto_video_00001.mp4",
                                                "subfolder": "auto-video",
                                                "type": "output",
                                            }
                                        ]
                                    }
                                }
                            }
                        }
                    )
                    return
                if parsed.path == "/view":
                    query = parse_qs(parsed.query)
                    records.append({"method": "VIEW_QUERY", "query": query})
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.end_headers()
                    self.wfile.write(response_media_body)
                    return
                self.send_error(404)

            def _json(self, payload: dict):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

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


def _workflow(tmp_path: Path) -> Path:
    workflow = {
        "218": {"class_type": "CLIPTextEncode", "inputs": {"text": "old negative"}},
        "224": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
        "228": {"class_type": "KSamplerAdvanced", "inputs": {"steps": 6, "cfg": 1}},
        "229": {"class_type": "KSamplerAdvanced", "inputs": {"steps": 6, "cfg": 1}},
        "230": {"class_type": "VHS_VideoCombine", "inputs": {"filename_prefix": "old", "frame_rate": 16}},
        "231": {"class_type": "Seed (rgthree)", "inputs": {"seed": -1}},
        "238": {"class_type": "INTConstant", "inputs": {"value": 5}},
        "248": {"class_type": "INTConstant", "inputs": {"value": 1024}},
        "257": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "old prompt"}},
        "_api_config": {"enabledParams": {"224:image": True}},
    }
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _payload(tmp_path: Path, *, refs: list[dict] | None = None) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    payload = {
        "job": {
            "id": "demo:S01:video:comfyui_wan",
            "project_name": "demo",
            "shot_id": "S01",
            "kind": "video",
            "provider": "comfyui_wan",
            "prompt": "cinematic tea steam rising",
            "negative_prompt": "watermark, bad hands",
            "duration": 3,
            "output_path": "generated/clips/S01.mp4",
            "refs": refs or [],
            "controls": {
                "width": 832,
                "height": 480,
                "fps": 12,
            },
        },
        "project_root": project.as_posix(),
        "output_path": (project / "generated" / "clips" / "S01.mp4").as_posix(),
        "references": refs or [],
    }
    path = tmp_path / "job.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _run_adapter(args: list[str], *, env: dict[str, str] | None = None):
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, SCRIPT.as_posix(), *args],
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )


def _run_adapter_module(args: list[str], *, env: dict[str, str] | None = None):
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "auto_video.comfyui_wan_adapter", *args],
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )


def test_comfyui_wan_adapter_patches_workflow_uploads_and_downloads_video(tmp_path: Path):
    image = tmp_path / "first-frame.png"
    image.write_bytes(b"fake-image")
    refs = [
        {
            "path": "assets/refs/first-frame.png",
            "absolute_path": image.as_posix(),
            "type": "image",
            "role": "first_frame",
            "usage": "preserve_subject",
            "exists": True,
        }
    ]
    job = _payload(tmp_path, refs=refs)
    workflow = _workflow(tmp_path)
    output = tmp_path / "out.mp4"

    with FakeComfyUIServer(media_body=b"adapter-video") as server:
        completed = _run_adapter(
            [
                "--base-url",
                server.url,
                "--workflow",
                workflow.as_posix(),
                "--seed",
                "123",
                "--steps",
                "8",
                "--guidance-scale",
                "1.25",
                "--job",
                job.as_posix(),
                "--project-root",
                (tmp_path / "project").as_posix(),
                "--output",
                output.as_posix(),
            ]
        )

    assert completed.returncode == 0, completed.stderr
    assert output.read_bytes() == b"adapter-video"
    prompt_record = next(record for record in server.records if record["path"] == "/prompt")
    prompt = json.loads(prompt_record["body"].decode("utf-8"))["prompt"]
    assert "_api_config" not in prompt
    assert prompt["224"]["inputs"]["image"] == "uploaded-first-frame.png"
    assert prompt["257"]["inputs"]["value"] == "cinematic tea steam rising"
    assert prompt["218"]["inputs"]["text"] == "watermark, bad hands"
    assert prompt["231"]["inputs"]["seed"] == 123
    assert prompt["238"]["inputs"]["value"] == 3
    assert prompt["248"]["inputs"]["value"] == 832
    assert prompt["230"]["inputs"]["frame_rate"] == 12
    assert prompt["228"]["inputs"]["steps"] == 8
    assert prompt["229"]["inputs"]["steps"] == 8
    assert prompt["228"]["inputs"]["cfg"] == 1.25
    view_query = next(record for record in server.records if record["method"] == "VIEW_QUERY")["query"]
    assert view_query["filename"] == ["auto_video_00001.mp4"]
    assert view_query["subfolder"] == ["auto-video"]
    assert view_query["type"] == ["output"]


def test_comfyui_wan_adapter_module_reads_base_url_and_workflow_from_env(tmp_path: Path):
    image = tmp_path / "first-frame.png"
    image.write_bytes(b"fake-image")
    job = _payload(
        tmp_path,
        refs=[
            {
                "absolute_path": image.as_posix(),
                "type": "image",
                "exists": True,
            }
        ],
    )
    workflow = _workflow(tmp_path)
    output = tmp_path / "out.mp4"

    with FakeComfyUIServer(media_body=b"module-video", history_empty_count=1) as server:
        completed = _run_adapter_module(
            [
                "--base-url-env",
                "COMFYUI_BASE_URL",
                "--workflow-env",
                "COMFYUI_WORKFLOW",
                "--poll-interval",
                "0.01",
                "--job",
                job.as_posix(),
                "--project-root",
                (tmp_path / "project").as_posix(),
                "--output",
                output.as_posix(),
            ],
            env={"COMFYUI_BASE_URL": server.url, "COMFYUI_WORKFLOW": workflow.as_posix()},
        )

    assert completed.returncode == 0, completed.stderr
    assert output.read_bytes() == b"module-video"


def test_comfyui_wan_adapter_requires_image_reference(tmp_path: Path):
    job = _payload(tmp_path, refs=[])
    workflow = _workflow(tmp_path)
    output = tmp_path / "out.mp4"

    with FakeComfyUIServer() as server:
        completed = _run_adapter(
            [
                "--base-url",
                server.url,
                "--workflow",
                workflow.as_posix(),
                "--job",
                job.as_posix(),
                "--project-root",
                (tmp_path / "project").as_posix(),
                "--output",
                output.as_posix(),
            ]
        )

    assert completed.returncode != 0
    assert "image reference" in completed.stderr
    assert not output.exists()


def test_comfyui_wan_adapter_works_through_external_command_provider(tmp_path: Path):
    project = tmp_path / "external-comfyui"
    (project / "assets" / "refs").mkdir(parents=True)
    (project / "assets" / "refs" / "S01.png").write_bytes(b"fake-image")
    workflow = _workflow(tmp_path)

    with FakeComfyUIServer(media_body=b"provider-video") as server:
        (project / "project.yaml").write_text(
            f"""
name: external_comfyui
width: 832
height: 480
fps: 12
default_video_provider: comfyui_wan
default_image_provider: mock
default_audio_provider: mock
providers:
  comfyui_wan:
    mode: external_command
    timeout_seconds: 30
    command:
      - {sys.executable}
      - {SCRIPT.as_posix()}
      - --base-url
      - {server.url}
      - --workflow
      - {workflow.as_posix()}
      - --poll-interval
      - "0.01"
""".lstrip(),
            encoding="utf-8",
        )
        (project / "shots.json").write_text(
            json.dumps(
                {
                    "shots": [
                        {
                            "id": "S01",
                            "duration": 2,
                            "provider": "comfyui_wan",
                            "visual_prompt": "steam rises",
                            "negative_prompt": "watermark",
                            "refs": [
                                {
                                    "path": "assets/refs/S01.png",
                                    "type": "image",
                                    "role": "first_frame",
                                    "usage": "preserve_subject",
                                }
                            ],
                        }
                    ]
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        results = submit_jobs(load_project(project), kind="video", provider_name="comfyui_wan")

    assert results[0].status == "succeeded"
    assert (project / "generated" / "clips" / "S01.mp4").read_bytes() == b"provider-video"
