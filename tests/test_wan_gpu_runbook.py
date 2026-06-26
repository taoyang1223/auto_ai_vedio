import json
import subprocess
import sys
from pathlib import Path

import pytest

from auto_video.errors import ConfigError
from auto_video.wan_gpu_runbook import (
    WanGpuRunbookOptions,
    build_wan_gpu_runbook,
    format_runbook_markdown,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "wan_gpu_runbook.py"


def test_build_wan_gpu_runbook_uses_remote_venv_entrypoints(tmp_path: Path):
    project = tmp_path / "demo"
    runbook = build_wan_gpu_runbook(
        WanGpuRunbookOptions(
            project=project,
            host="gpu-box",
            remote_dir="/data/auto-video/jobs/demo",
            ssh_options=("StrictHostKeyChecking=no",),
        )
    )

    assert runbook["dry_run"] is True
    assert [phase["name"] for phase in runbook["phases"]] == [
        "rent_gpu",
        "install_auto_video",
        "start_wan_http",
        "preflight",
        "generate",
        "collect",
        "shutdown",
    ]
    install = runbook["phases"][1]["commands"]["sync_and_install"][0]
    assert install[:4] == ["ssh", "-o", "StrictHostKeyChecking=no", "gpu-box"]
    assert "git clone" in install[-1]
    assert "/opt/auto-ai-video/.venv/bin/python" in install[-1]

    smoke = runbook["smoke"]["commands"]
    assert "--remote-auto-video" in smoke["remote_doctor"]
    assert "/opt/auto-ai-video/.venv/bin/auto-video" in smoke["remote_doctor"]
    assert smoke["wan_runtime_doctor"][4:8] == [
        "WAN_BASE_URL=http://127.0.0.1:8082",
        "/opt/auto-ai-video/.venv/bin/python",
        "-m",
        "auto_video.wan_runtime_doctor",
    ]
    assert smoke["remote_run"][-2:] == ["--remote-env", "WAN_BASE_URL=http://127.0.0.1:8082"]


def test_wan_gpu_runbook_keeps_wan_start_manual_by_default(tmp_path: Path):
    runbook = build_wan_gpu_runbook(
        WanGpuRunbookOptions(
            project=tmp_path / "demo",
            host="gpu-box",
            remote_dir="/data/auto-video/jobs/demo",
        )
    )

    start_phase = runbook["phases"][2]
    assert start_phase["name"] == "start_wan_http"
    assert "manual_action" in start_phase
    assert "GET /health" in start_phase["manual_action"]
    assert "commands" not in start_phase


def test_wan_gpu_runbook_includes_explicit_wan_start_command(tmp_path: Path):
    runbook = build_wan_gpu_runbook(
        WanGpuRunbookOptions(
            project=tmp_path / "demo",
            host="gpu-box",
            remote_dir="/data/auto-video/jobs/demo",
            wan_start_command="nohup python /root/wan_server.py --mode i2v --port 8082 > /tmp/wan.log 2>&1 &",
        )
    )

    start_command = runbook["phases"][2]["commands"]["start"][0]
    assert start_command[:3] == ["ssh", "gpu-box", "bash"]
    assert "wan_server.py" in start_command[-1]
    assert "tail -n 80 /tmp/wan_server.log" in runbook["phases"][2]["notes"][0]


def test_wan_gpu_runbook_rejects_unsafe_remote_dir(tmp_path: Path):
    with pytest.raises(ConfigError):
        build_wan_gpu_runbook(
            WanGpuRunbookOptions(
                project=tmp_path / "demo",
                host="gpu-box",
                remote_dir="/data/../demo",
            )
        )


def test_format_runbook_markdown_contains_copyable_commands(tmp_path: Path):
    runbook = build_wan_gpu_runbook(
        WanGpuRunbookOptions(
            project=tmp_path / "demo",
            host="gpu-box",
            remote_dir="/data/auto-video/jobs/demo",
            wan_start_command="nohup python /root/wan_server.py --mode i2v --port 8082 > /tmp/wan.log 2>&1 &",
        )
    )

    markdown = format_runbook_markdown(runbook)

    assert markdown.startswith("# Wan GPU Runbook")
    assert "```bash" in markdown
    assert "auto_video.wan_runtime_doctor" in markdown
    assert "WAN_BASE_URL=http://127.0.0.1:8082" in markdown


def test_wan_gpu_runbook_script_prints_json(tmp_path: Path):
    completed = subprocess.run(
        [
            sys.executable,
            SCRIPT.as_posix(),
            "--project",
            (tmp_path / "demo").as_posix(),
            "--host",
            "gpu-box",
            "--remote-dir",
            "/data/auto-video/jobs/demo",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["host"] == "gpu-box"
    assert payload["smoke"]["commands"]["wan_runtime_doctor"][3:6] == [
        "/opt/auto-ai-video/.venv/bin/python",
        "-m",
        "auto_video.wan_runtime_doctor",
    ]


def test_wan_gpu_runbook_module_prints_markdown(tmp_path: Path):
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "auto_video.wan_gpu_runbook",
            "--project",
            (tmp_path / "demo").as_posix(),
            "--host",
            "gpu-box",
            "--remote-dir",
            "/data/auto-video/jobs/demo",
            "--format",
            "markdown",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith("# Wan GPU Runbook")
    assert "## 1. Rent GPU" in completed.stdout
    assert "python -m auto_video.wan_runtime_doctor" in completed.stdout
