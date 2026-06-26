import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from auto_video.pipeline import submit_jobs
from auto_video.project import load_project

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "scripts" / "wan_http_adapter.py"


class FakeWanServer:
    def __init__(self, *, content_type: str = "video/mp4", body: bytes = b"mp4-bytes", status: int = 200):
        self.records: list[dict] = []
        records = self.records
        response_content_type = content_type
        response_body = body
        response_status = status

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                records.append(
                    {
                        "path": self.path,
                        "headers": dict(self.headers),
                        "body": json.loads(raw_body.decode("utf-8")),
                    }
                )
                self.send_response(response_status)
                self.send_header("Content-Type", response_content_type)
                self.end_headers()
                self.wfile.write(response_body)

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


def _payload(
    tmp_path: Path,
    *,
    refs: list[dict] | None = None,
    duration: float = 2.0,
    fps: int = 12,
) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    payload = {
        "job": {
            "id": "demo:S01:video:wan_http",
            "project_name": "demo",
            "shot_id": "S01",
            "kind": "video",
            "provider": "wan_http",
            "prompt": "cinematic tea steam rising",
            "negative_prompt": "watermark, bad hands",
            "duration": duration,
            "output_path": "generated/clips/S01.mp4",
            "refs": refs or [],
            "controls": {
                "visual_prompt": "cinematic tea steam rising",
                "camera_motion": "slow dolly in",
                "environment_motion": "steam drifts",
                "performance": "",
                "lighting": "warm rim light",
                "audio_intent": "",
                "subtitle": "",
                "negative_prompt": "watermark, bad hands",
                "aspect_ratio": "9:16",
                "width": 832,
                "height": 480,
                "fps": fps,
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
        [sys.executable, ADAPTER.as_posix(), *args],
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
        [sys.executable, "-m", "auto_video.wan_http_adapter", *args],
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )


def test_wan_http_adapter_posts_i2v_with_image_reference(tmp_path: Path):
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
    job = _payload(tmp_path, refs=refs, duration=2.0, fps=12)
    output = tmp_path / "out.mp4"

    with FakeWanServer(body=b"i2v-mp4") as server:
        completed = _run_adapter(
            [
                "--base-url",
                server.url,
                "--steps",
                "18",
                "--guidance-scale",
                "4.5",
                "--seed",
                "123",
                "--job",
                job.as_posix(),
                "--project-root",
                (tmp_path / "project").as_posix(),
                "--output",
                output.as_posix(),
            ]
        )

    assert completed.returncode == 0, completed.stderr
    assert output.read_bytes() == b"i2v-mp4"
    assert server.records[0]["path"] == "/i2v"
    body = server.records[0]["body"]
    assert body["prompt"] == "cinematic tea steam rising"
    assert body["negative_prompt"] == "watermark, bad hands"
    assert body["num_frames"] == 24
    assert body["num_inference_steps"] == 18
    assert body["guidance_scale"] == 4.5
    assert body["seed"] == 123
    assert body["width"] == 832
    assert body["height"] == 480
    assert body["fps"] == 12
    assert body["image_base64"]


def test_wan_http_adapter_posts_t2v_without_image_reference(tmp_path: Path):
    job = _payload(tmp_path, refs=[], duration=5.0, fps=24)
    output = tmp_path / "out.mp4"

    with FakeWanServer(body=b"t2v-mp4") as server:
        completed = _run_adapter(
            [
                "--base-url",
                server.url,
                "--frames",
                "33",
                "--job",
                job.as_posix(),
                "--project-root",
                (tmp_path / "project").as_posix(),
                "--output",
                output.as_posix(),
            ]
        )

    assert completed.returncode == 0, completed.stderr
    assert output.read_bytes() == b"t2v-mp4"
    assert server.records[0]["path"] == "/t2v"
    body = server.records[0]["body"]
    assert body["num_frames"] == 33
    assert "image_base64" not in body


def test_wan_http_adapter_module_entrypoint_posts_t2v(tmp_path: Path):
    job = _payload(tmp_path, refs=[], duration=1.0, fps=10)
    output = tmp_path / "out.mp4"

    with FakeWanServer(body=b"module-mp4") as server:
        completed = _run_adapter_module(
            [
                "--base-url",
                server.url,
                "--job",
                job.as_posix(),
                "--project-root",
                (tmp_path / "project").as_posix(),
                "--output",
                output.as_posix(),
            ]
        )

    assert completed.returncode == 0, completed.stderr
    assert output.read_bytes() == b"module-mp4"
    assert server.records[0]["path"] == "/t2v"


def test_wan_http_adapter_reads_base_url_and_token_from_env(tmp_path: Path):
    job = _payload(tmp_path, refs=[])
    output = tmp_path / "out.mp4"

    with FakeWanServer() as server:
        completed = _run_adapter(
            [
                "--base-url-env",
                "WAN_BASE_URL",
                "--token-env",
                "WAN_TOKEN",
                "--job",
                job.as_posix(),
                "--project-root",
                (tmp_path / "project").as_posix(),
                "--output",
                output.as_posix(),
            ],
            env={"WAN_BASE_URL": server.url, "WAN_TOKEN": "secret-token"},
        )

    assert completed.returncode == 0, completed.stderr
    assert server.records[0]["headers"]["Authorization"] == "Bearer secret-token"


def test_wan_http_adapter_json_response_is_failure(tmp_path: Path):
    job = _payload(tmp_path, refs=[])
    output = tmp_path / "out.mp4"

    with FakeWanServer(content_type="application/json", body=b'{"error": "bad request"}') as server:
        completed = _run_adapter(
            [
                "--base-url",
                server.url,
                "--job",
                job.as_posix(),
                "--project-root",
                (tmp_path / "project").as_posix(),
                "--output",
                output.as_posix(),
            ]
        )

    assert completed.returncode != 0
    assert "bad request" in completed.stderr
    assert not output.exists()


def test_wan_http_adapter_works_through_external_command_provider(tmp_path: Path):
    project = tmp_path / "external-wan"
    (project / "assets" / "refs").mkdir(parents=True)
    (project / "assets" / "refs" / "S01.png").write_bytes(b"fake-image")

    with FakeWanServer(body=b"provider-mp4") as server:
        (project / "project.yaml").write_text(
            f"""
name: external_wan
width: 832
height: 480
fps: 12
default_video_provider: wan_http
default_image_provider: mock
default_audio_provider: mock
providers:
  wan_http:
    mode: external_command
    timeout_seconds: 30
    command:
      - {sys.executable}
      - {ADAPTER.as_posix()}
      - --base-url
      - {server.url}
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
                            "provider": "wan_http",
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
        results = submit_jobs(load_project(project), kind="video", provider_name="wan_http")

    assert results[0].status == "succeeded"
    assert (project / "generated" / "clips" / "S01.mp4").read_bytes() == b"provider-mp4"
    assert server.records[0]["path"] == "/i2v"
