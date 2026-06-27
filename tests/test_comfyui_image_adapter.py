import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from auto_video.first_frame_generation import generate_first_frames
from auto_video.project import load_project

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "comfyui_image_adapter.py"


class FakeComfyUIServer:
    def __init__(self, *, media_body: bytes = b"comfy-png", history_empty_count: int = 0):
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
                if self.path == "/prompt":
                    self._json({"prompt_id": "prompt-image-123"})
                    return
                self.send_error(404)

            def do_GET(self):
                records.append({"method": "GET", "path": self.path, "headers": dict(self.headers)})
                parsed = urlparse(self.path)
                if parsed.path == "/history/prompt-image-123":
                    if empty_count["remaining"] > 0:
                        empty_count["remaining"] -= 1
                        self._json({})
                        return
                    self._json(
                        {
                            "prompt-image-123": {
                                "outputs": {
                                    "499": {
                                        "images": [
                                            {
                                                "filename": "first_frame_00001.png",
                                                "subfolder": "auto_video/first_frames",
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
                    self.send_header("Content-Type", "image/png")
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
        "3": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 4, "cfg": 1}},
        "118": {
            "class_type": "CR SDXL Aspect Ratio",
            "inputs": {"width": 512, "height": 512, "aspect_ratio": "custom", "batch_size": 1},
        },
        "187": {"class_type": "CLIPTextEncode", "inputs": {"text": "old prompt"}},
        "437": {"class_type": "CLIPTextEncode", "inputs": {"text": "old negative"}},
        "499": {"class_type": "SaveImage", "inputs": {"filename_prefix": "old"}},
    }
    path = tmp_path / "image-workflow.json"
    path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _payload(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    payload = {
        "job": {
            "id": "demo:S01:image:comfyui_image",
            "project_name": "demo",
            "shot_id": "S01",
            "kind": "image",
            "provider": "comfyui_image",
            "prompt": "cinematic first frame, creator in studio",
            "negative_prompt": "watermark, bad hands",
            "duration": None,
            "output_path": "generated/images/S01.png",
            "refs": [],
            "controls": {
                "width": 832,
                "height": 544,
                "fps": 16,
            },
        },
        "project_root": project.as_posix(),
        "output_path": (project / "generated" / "images" / "S01.png").as_posix(),
        "references": [],
    }
    path = tmp_path / "job.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _run_adapter_module(args: list[str], *, env: dict[str, str] | None = None):
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "auto_video.comfyui_image_adapter", *args],
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )


def test_comfyui_image_adapter_patches_workflow_and_downloads_image(tmp_path: Path):
    job = _payload(tmp_path)
    workflow = _workflow(tmp_path)
    output = tmp_path / "out.png"

    with FakeComfyUIServer(media_body=b"adapter-image", history_empty_count=1) as server:
        completed = subprocess.run(
            [
                sys.executable,
                SCRIPT.as_posix(),
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
                "--poll-interval",
                "0.01",
                "--job",
                job.as_posix(),
                "--project-root",
                (tmp_path / "project").as_posix(),
                "--output",
                output.as_posix(),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    assert completed.returncode == 0, completed.stderr
    assert output.read_bytes() == b"adapter-image"
    prompt_record = next(record for record in server.records if record["path"] == "/prompt")
    prompt = json.loads(prompt_record["body"].decode("utf-8"))["prompt"]
    assert prompt["187"]["inputs"]["text"] == "cinematic first frame, creator in studio"
    assert prompt["437"]["inputs"]["text"] == "watermark, bad hands"
    assert prompt["3"]["inputs"]["seed"] == 123
    assert prompt["3"]["inputs"]["steps"] == 8
    assert prompt["3"]["inputs"]["cfg"] == 1.25
    assert prompt["118"]["inputs"]["width"] == 832
    assert prompt["118"]["inputs"]["height"] == 544
    assert prompt["499"]["inputs"]["filename_prefix"].startswith("auto_video/first_frames/demo_S01_image_comfyui_image")
    view_query = next(record for record in server.records if record["method"] == "VIEW_QUERY")["query"]
    assert view_query["filename"] == ["first_frame_00001.png"]
    assert view_query["subfolder"] == ["auto_video/first_frames"]


def test_comfyui_image_adapter_uses_workflow_profile(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    workflow = _workflow(tmp_path)
    output = tmp_path / "out.png"
    job = _payload(tmp_path)
    (project / "project.yaml").write_text(
        f"""
name: image_profile_demo
width: 832
height: 544
fps: 16
default_video_provider: mock
default_image_provider: comfyui_image
providers:
  comfyui_image:
    mode: external_command
comfyui_workflows:
  custom_t2i:
    provider: comfyui_image
    kind: text_to_image
    workflow_path: {workflow.as_posix()}
    parameters:
      seed: 777
      steps: 9
      guidance_scale: 1.75
    nodes:
      prompt:
        id: "187"
        input: text
      negative:
        id: "437"
        input: text
      seed:
        id: "3"
        input: seed
      size:
        id: "118"
        width_input: width
        height_input: height
      output:
        id: "499"
        filename_prefix_input: filename_prefix
      steps:
        ids:
          - "3"
        steps_input: steps
        cfg_input: cfg
""".lstrip(),
        encoding="utf-8",
    )
    (project / "shots.json").write_text('{"shots":[{"id":"S01","duration":2,"visual_prompt":"x"}]}', encoding="utf-8")

    with FakeComfyUIServer(media_body=b"profile-image") as server:
        completed = _run_adapter_module(
            [
                "--base-url",
                server.url,
                "--workflow-profile",
                "custom_t2i",
                "--poll-interval",
                "0.01",
                "--job",
                job.as_posix(),
                "--project-root",
                project.as_posix(),
                "--output",
                output.as_posix(),
            ]
        )

    assert completed.returncode == 0, completed.stderr
    assert output.read_bytes() == b"profile-image"
    prompt_record = next(record for record in server.records if record["path"] == "/prompt")
    prompt = json.loads(prompt_record["body"].decode("utf-8"))["prompt"]
    assert prompt["3"]["inputs"]["seed"] == 777
    assert prompt["3"]["inputs"]["steps"] == 9
    assert prompt["3"]["inputs"]["cfg"] == 1.75


def test_comfyui_image_adapter_works_through_external_provider_and_promotes_ref(tmp_path: Path):
    project = tmp_path / "external-comfyui-image"
    workflow = _workflow(tmp_path)

    with FakeComfyUIServer(media_body=b"\x89PNG\r\n\x1a\nprovider-image") as server:
        (project / "assets" / "refs").mkdir(parents=True)
        (project / "project.yaml").write_text(
            f"""
name: external_comfyui_image
width: 832
height: 544
fps: 16
default_video_provider: mock
default_image_provider: comfyui_image
default_audio_provider: mock
providers:
  comfyui_image:
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
                            "visual_prompt": "first frame prompt",
                            "negative_prompt": "watermark",
                        }
                    ]
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        result = generate_first_frames(load_project(project), provider_name="comfyui_image", only={"S01"})

    assert result["count"] == 1
    assert result["first_frames"]["promoted"][0]["path"] == "assets/refs/S01_first_frame.png"
    assert (project / "generated" / "images" / "S01.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert (project / "assets" / "refs" / "S01_first_frame.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
