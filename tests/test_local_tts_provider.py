import subprocess
from pathlib import Path

from auto_video.job_builder import build_jobs
from auto_video.models import ProviderConfig
from auto_video.project import load_project
from auto_video.providers.local_tts import LocalTTSProvider


class FakeTTSRunner:
    def __init__(self):
        self.commands = []

    def run(self, command, *, cwd: Path, timeout: int):
        self.commands.append(tuple(command))
        output = Path(command[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"RIFFfake-wav")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")


def test_local_tts_silence_engine_writes_audio(demo_project_files):
    project = load_project(demo_project_files)
    job = build_jobs(project, kind="audio", provider_name="local_tts")[0]
    runner = FakeTTSRunner()
    provider = LocalTTSProvider(
        "local_tts",
        ProviderConfig(mode="local_tts", timeout_seconds=30, options={"engine": "silence", "sample_rate": 16000, "channels": 1}),
        runner,
    )

    result = provider.execute_job(job, project.config.root)

    assert result.status == "succeeded"
    assert result.kind == "audio"
    assert result.path == demo_project_files / "generated" / "audio" / "S01.wav"
    assert result.path.read_bytes().startswith(b"RIFF")
    assert runner.commands[0][:4] == ("ffmpeg", "-y", "-f", "lavfi")
    assert result.metadata["local_tts"]["reason"] == "engine_silence"


def test_local_tts_edge_command_uses_subtitle_text(demo_project_files, monkeypatch):
    monkeypatch.setattr("auto_video.providers.local_tts.shutil.which", lambda _command: "/usr/local/bin/edge-tts")
    project = load_project(demo_project_files)
    job = build_jobs(project, kind="audio", provider_name="local_tts")[0]
    runner = FakeTTSRunner()
    provider = LocalTTSProvider(
        "local_tts",
        ProviderConfig(mode="local_tts", timeout_seconds=30, options={"engine": "edge_tts", "voice": "zh-CN-XiaoxiaoNeural"}),
        runner,
    )

    result = provider.execute_job(job, project.config.root)

    assert result.status == "succeeded"
    assert runner.commands[0][0] == "edge-tts"
    assert "--text" in runner.commands[0]
    assert runner.commands[0][runner.commands[0].index("--text") + 1] == "Late night again"
    assert runner.commands[1][0] == "ffmpeg"
    assert result.metadata["local_tts"]["voice"] == "zh-CN-XiaoxiaoNeural"
