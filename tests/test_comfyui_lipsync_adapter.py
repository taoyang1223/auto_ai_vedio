import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class FakeComfyUILipSyncServer:
    def __init__(self, *, media_body: bytes = b"synced-video"):
        self.records: list[dict] = []
        records = self.records
        response_media_body = media_body

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
                    name = "uploaded-audio.wav" if b"fake-audio" in raw_body else "uploaded-video.mp4"
                    self._json({"name": name, "subfolder": "", "type": "input"})
                    return
                if self.path == "/prompt":
                    self._json({"prompt_id": "prompt-lipsync"})
                    return
                self.send_error(404)

            def do_GET(self):
                records.append({"method": "GET", "path": self.path, "headers": dict(self.headers)})
                parsed = urlparse(self.path)
                if parsed.path == "/history/prompt-lipsync":
                    self._json(
                        {
                            "prompt-lipsync": {
                                "outputs": {
                                    "12": {
                                        "videos": [
                                            {
                                                "filename": "lipsync_00001.mp4",
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
        "10": {"class_type": "LoadVideo", "inputs": {"source_video": "old.mp4"}},
        "11": {"class_type": "LoadAudio", "inputs": {"source_audio": "old.wav"}},
        "12": {"class_type": "SaveVideo", "inputs": {"prefix": "old"}},
        "13": {"class_type": "LipSyncSampler", "inputs": {"sample_steps": 4, "cfg_scale": 1}},
    }
    path = tmp_path / "lipsync-workflow.json"
    path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _payload(tmp_path: Path, video: Path, audio: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    payload = {
        "job": {
            "id": "demo:S01:lipsync:comfyui_lipsync",
            "project_name": "demo",
            "shot_id": "S01",
            "kind": "lipsync",
            "provider": "comfyui_lipsync",
            "prompt": "lip-sync pass",
            "duration": 3,
            "output_path": "generated/lipsync/S01.mp4",
            "refs": [],
            "controls": {"fps": 16},
        },
        "project_root": project.as_posix(),
        "output_path": (project / "generated" / "lipsync" / "S01.mp4").as_posix(),
        "references": [
            {
                "path": "generated/clips/S01.mp4",
                "absolute_path": video.as_posix(),
                "type": "video",
                "role": "source_video",
                "usage": "provide_context",
                "exists": True,
            },
            {
                "path": "generated/audio/S01.wav",
                "absolute_path": audio.as_posix(),
                "type": "audio",
                "role": "source_audio",
                "usage": "provide_context",
                "exists": True,
            },
        ],
    }
    path = tmp_path / "job.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _run_adapter_module(args: list[str], *, env: dict[str, str] | None = None):
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "auto_video.comfyui_lipsync_adapter", *args],
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )


def test_comfyui_lipsync_adapter_patches_video_audio_and_downloads(tmp_path: Path):
    video = tmp_path / "source.mp4"
    audio = tmp_path / "voice.wav"
    video.write_bytes(b"fake-video")
    audio.write_bytes(b"fake-audio")
    job = _payload(tmp_path, video, audio)
    workflow = _workflow(tmp_path)
    output = tmp_path / "out.mp4"

    with FakeComfyUILipSyncServer(media_body=b"pixel-synced") as server:
        completed = _run_adapter_module(
            [
                "--base-url",
                server.url,
                "--workflow",
                workflow.as_posix(),
                "--video-node",
                "10",
                "--video-input",
                "source_video",
                "--audio-node",
                "11",
                "--audio-input",
                "source_audio",
                "--output-node",
                "12",
                "--filename-prefix-input",
                "prefix",
                "--steps-node",
                "13",
                "--steps-input",
                "sample_steps",
                "--cfg-input",
                "cfg_scale",
                "--steps",
                "8",
                "--guidance-scale",
                "1.5",
                "--job",
                job.as_posix(),
                "--project-root",
                (tmp_path / "project").as_posix(),
                "--output",
                output.as_posix(),
            ]
        )

    assert completed.returncode == 0, completed.stderr
    assert output.read_bytes() == b"pixel-synced"
    prompt_record = next(record for record in server.records if record["method"] == "POST" and record["path"] == "/prompt")
    prompt = json.loads(prompt_record["body"].decode("utf-8"))["prompt"]
    assert prompt["10"]["inputs"]["source_video"] == "uploaded-video.mp4"
    assert prompt["11"]["inputs"]["source_audio"] == "uploaded-audio.wav"
    assert prompt["12"]["inputs"]["prefix"].startswith("auto_video/lipsync/demo_S01_lipsync_comfyui_lipsync")
    assert prompt["13"]["inputs"]["sample_steps"] == 8
    assert prompt["13"]["inputs"]["cfg_scale"] == 1.5
    view_record = next(record for record in server.records if record["method"] == "VIEW_QUERY")
    assert view_record["query"]["filename"] == ["lipsync_00001.mp4"]
