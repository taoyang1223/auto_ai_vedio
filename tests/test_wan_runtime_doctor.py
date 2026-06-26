import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCTOR = ROOT / "scripts" / "wan_runtime_doctor.py"


class FakeHealthServer:
    def __init__(self, payload: dict, *, status: int = 200):
        self.records: list[dict] = []
        records = self.records
        response_payload = payload
        response_status = status

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                records.append({"path": self.path, "headers": dict(self.headers)})
                self.send_response(response_status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response_payload).encode("utf-8"))

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


def test_wan_runtime_doctor_healthy_service_exits_zero():
    with FakeHealthServer(
        {
            "status": "ok",
            "i2v_loaded": True,
            "t2v_loaded": True,
            "gpu_free_gb": 28.5,
            "offload": False,
            "tf32": True,
        }
    ) as server:
        completed = _run_doctor(["--base-url", server.url, "--require-i2v", "--require-t2v"])

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["base_url"] == server.url
    assert [check["status"] for check in payload["checks"]] == ["ok", "ok", "ok", "ok"]
    health = next(check for check in payload["checks"] if check["name"] == "health")
    assert health["details"]["gpu_free_gb"] == 28.5
    assert server.records[0]["path"] == "/health"


def test_wan_runtime_doctor_sends_bearer_token_from_env():
    with FakeHealthServer({"status": "ok", "i2v_loaded": True}) as server:
        completed = _run_doctor(
            ["--base-url-env", "WAN_BASE_URL", "--token-env", "WAN_TOKEN"],
            env={"WAN_BASE_URL": server.url, "WAN_TOKEN": "secret-token"},
        )

    assert completed.returncode == 0, completed.stderr
    assert server.records[0]["headers"]["Authorization"] == "Bearer secret-token"
    assert "secret-token" not in completed.stdout


def test_wan_runtime_doctor_require_i2v_failure_exits_one():
    with FakeHealthServer({"status": "ok", "i2v_loaded": False, "t2v_loaded": True}) as server:
        completed = _run_doctor(["--base-url", server.url, "--require-i2v"])

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["ok"] is False
    i2v = next(check for check in payload["checks"] if check["name"] == "i2v_loaded")
    assert i2v["status"] == "failed"


def test_wan_runtime_doctor_require_t2v_failure_exits_one():
    with FakeHealthServer({"status": "ok", "i2v_loaded": True, "t2v_loaded": False}) as server:
        completed = _run_doctor(["--base-url", server.url, "--require-t2v"])

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    t2v = next(check for check in payload["checks"] if check["name"] == "t2v_loaded")
    assert t2v["status"] == "failed"


def test_wan_runtime_doctor_missing_base_url_env_exits_one():
    completed = _run_doctor(["--base-url-env", "WAN_BASE_URL_MISSING"], env={"WAN_BASE_URL_MISSING": ""})

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["ok"] is False
    assert payload["checks"][0]["name"] == "base_url"
    assert payload["checks"][0]["status"] == "failed"
    assert "WAN_BASE_URL_MISSING" in payload["checks"][0]["message"]
