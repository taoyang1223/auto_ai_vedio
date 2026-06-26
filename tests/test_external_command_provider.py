import json
import sys
from pathlib import Path

import pytest

from auto_video.errors import ConfigError
from auto_video.job_builder import build_jobs
from auto_video.pipeline import submit_jobs
from auto_video.project import load_project
from auto_video.providers.external_command import ExternalCommandProvider
from auto_video.worker_bundle import export_worker_bundle, import_worker_results
from auto_video.worker_runner import run_worker_bundle


def _write_adapter(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _external_project(tmp_path: Path, adapter: Path) -> Path:
    project = tmp_path / "external-demo"
    (project / "assets" / "refs").mkdir(parents=True)
    (project / "assets" / "refs" / "S01.txt").write_text("reference frame\n", encoding="utf-8")
    (project / "project.yaml").write_text(
        f"""
name: external_demo
aspect_ratio: "9:16"
width: 720
height: 1280
fps: 24
default_video_provider: local_wan
default_image_provider: mock
default_audio_provider: mock
providers:
  local_wan:
    mode: external_command
    timeout_seconds: 30
    command:
      - {sys.executable}
      - {adapter.as_posix()}
""".lstrip(),
        encoding="utf-8",
    )
    (project / "shots.json").write_text(
        json.dumps(
            {
                "shots": [
                    {
                        "id": "S01",
                        "title": "Hook",
                        "duration": 5,
                        "provider": "local_wan",
                        "visual_prompt": "A cinematic product reveal",
                        "camera_motion": "slow dolly in",
                        "environment_motion": "dust and light move through the air",
                        "performance": "hands move gently",
                        "lighting": "warm rim light",
                        "audio_intent": "soft room tone",
                        "subtitle": "Quiet power",
                        "negative_prompt": "watermark, distorted hands",
                        "refs": [
                            {
                                "path": "assets/refs/S01.txt",
                                "type": "text",
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
    return project


def test_external_command_provider_executes_adapter_and_records_payload(tmp_path: Path):
    payload_copy = tmp_path / "payload.json"
    adapter = _write_adapter(
        tmp_path / "adapter.py",
        f"""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--job", required=True)
parser.add_argument("--project-root", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()

payload = json.loads(Path(args.job).read_text(encoding="utf-8"))
Path({str(payload_copy)!r}).write_text(json.dumps(payload, indent=2), encoding="utf-8")
Path(args.output).parent.mkdir(parents=True, exist_ok=True)
Path(args.output).write_text("external video for " + payload["job"]["shot_id"], encoding="utf-8")
print("adapter ok")
""".lstrip(),
    )
    project = load_project(_external_project(tmp_path, adapter))

    results = submit_jobs(project, kind="video", provider_name="local_wan")

    result = results[0]
    assert result.status == "succeeded"
    assert result.provider == "local_wan"
    assert result.path == project.config.root / "generated" / "clips" / "S01.mp4"
    assert result.path.read_text(encoding="utf-8") == "external video for S01"
    assert result.metadata["external_command"]["returncode"] == 0
    assert "adapter ok" in result.metadata["external_command"]["stdout"]

    payload = json.loads(payload_copy.read_text(encoding="utf-8"))
    assert payload["job"]["provider"] == "local_wan"
    assert payload["job"]["controls"]["camera_motion"] == "slow dolly in"
    assert payload["job"]["controls"]["width"] == 720
    assert payload["references"][0]["absolute_path"].endswith("assets/refs/S01.txt")
    assert payload["references"][0]["exists"] is True

    manifest = json.loads((project.config.root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["jobs"]["external_demo:S01:video:local_wan"]["status"] == "succeeded"
    assert manifest["shots"]["S01"]["provider"] == "local_wan"
    assert manifest["shots"]["S01"]["clip"] == "generated/clips/S01.mp4"


def test_external_command_provider_failure_is_recorded(tmp_path: Path):
    adapter = _write_adapter(
        tmp_path / "adapter_fail.py",
        """
import sys

print("adapter failed", file=sys.stderr)
sys.exit(7)
""".lstrip(),
    )
    project = load_project(_external_project(tmp_path, adapter))

    results = submit_jobs(project, kind="video", provider_name="local_wan")

    result = results[0]
    assert result.status == "failed"
    assert result.path is None
    assert result.error == "external command failed with exit code 7"
    assert result.metadata["external_command"]["returncode"] == 7
    assert "adapter failed" in result.metadata["external_command"]["stderr"]

    manifest = json.loads((project.config.root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["jobs"]["external_demo:S01:video:local_wan"]["status"] == "failed"
    assert "S01" not in manifest.get("clips", {})


def test_external_command_provider_timeout_is_retryable(tmp_path: Path):
    adapter = _write_adapter(
        tmp_path / "adapter_timeout.py",
        """
import time

time.sleep(2)
""".lstrip(),
    )
    project = load_project(_external_project(tmp_path, adapter))
    config = project.config.providers["local_wan"]
    job = build_jobs(project, kind="video", provider_name="local_wan")[0]

    short_timeout_config = type(config)(
        mode=config.mode,
        endpoint_env=config.endpoint_env,
        token_env=config.token_env,
        timeout_seconds=1,
        max_attempts=config.max_attempts,
        options=config.options,
    )
    provider = ExternalCommandProvider("local_wan", short_timeout_config)
    result = provider.execute_job(job, project.config.root)

    assert result.status == "retryable_failed"
    assert result.retryable is True
    assert result.error == "external command timed out after 1 seconds"


def test_external_command_provider_rejects_unsafe_command_config(tmp_path: Path):
    project = load_project(_external_project(tmp_path, tmp_path / "adapter.py"))
    config = project.config.providers["local_wan"]
    bad_config = type(config)(
        mode=config.mode,
        endpoint_env=config.endpoint_env,
        token_env=config.token_env,
        timeout_seconds=config.timeout_seconds,
        max_attempts=config.max_attempts,
        options={"command": []},
    )

    with pytest.raises(ConfigError) as exc:
        ExternalCommandProvider("local_wan", bad_config)

    assert "command" in str(exc.value)


def test_worker_bundle_runs_external_command_provider(tmp_path: Path):
    adapter = _write_adapter(
        tmp_path / "adapter_worker.py",
        """
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--job", required=True)
parser.add_argument("--project-root", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()
payload = json.loads(Path(args.job).read_text(encoding="utf-8"))
Path(args.output).parent.mkdir(parents=True, exist_ok=True)
Path(args.output).write_text("worker external " + payload["job"]["shot_id"], encoding="utf-8")
""".lstrip(),
    )
    project = load_project(_external_project(tmp_path, adapter))
    bundle = tmp_path / "bundle"

    export_worker_bundle(project, bundle, kind="video", provider_name="local_wan", force=True)
    run_worker_bundle(bundle)
    import_summary = import_worker_results(project.config.root, bundle)

    assert import_summary["imported"] == ["external_demo:S01:video:local_wan"]
    assert (project.config.root / "generated" / "clips" / "S01.mp4").read_text(encoding="utf-8") == (
        "worker external S01"
    )
