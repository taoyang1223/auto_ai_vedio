from auto_video.remote_transport import CommandResult
from auto_video.remote_wrapup import RemoteWrapupOptions, build_remote_wrapup_plan, run_remote_wrapup


class WrapupRunner:
    def __init__(self, *, busy: bool = False):
        self.busy = busy
        self.commands: list[tuple[str, ...]] = []

    def run(self, command):
        command = tuple(command)
        self.commands.append(command)
        if "du" in command:
            return CommandResult(command=command, stdout="12M\t/root/auto-video/jobs/demo\n")
        if "df" in command:
            return CommandResult(command=command, stdout="Filesystem Size Used Avail Use% Mounted on\n/dev/sda 30G 16G 14G 54% /\n")
        if "curl" in command:
            stdout = '{"queue_running": [["job"]], "queue_pending": []}' if self.busy else '{"queue_running": [], "queue_pending": []}'
            return CommandResult(command=command, stdout=stdout)
        if "nvidia-smi" in command:
            stdout = "1200, 32607, 40\n" if self.busy else "620, 32607, 0\n"
            return CommandResult(command=command, stdout=stdout)
        return CommandResult(command=command, stdout="ok\n")


def test_build_remote_wrapup_plan_includes_cost_checks():
    plan = build_remote_wrapup_plan(
        RemoteWrapupOptions(
            host="gpu-box",
            remote_dir="/root/auto-video/jobs/demo",
            ssh_options=("Port=13159",),
        )
    )

    assert plan.host == "gpu-box"
    assert plan.remote_dir == "/root/auto-video/jobs/demo"
    assert [check.name for check in plan.checks] == [
        "remote_job_dir_size",
        "remote_disk_free",
        "comfyui_queue",
        "gpu_status",
    ]
    assert plan.checks[2].commands == (
        ("ssh", "-o", "Port=13159", "gpu-box", "curl", "-fsS", "http://127.0.0.1:6006/queue"),
    )


def test_run_remote_wrapup_dry_run_plans_without_commands():
    runner = WrapupRunner()

    report = run_remote_wrapup(
        RemoteWrapupOptions(host="gpu-box", remote_dir="/root/auto-video/jobs/demo"),
        runner=runner,
        dry_run=True,
    )

    assert report["ok"] is True
    assert report["dry_run"] is True
    assert runner.commands == []
    assert [check["status"] for check in report["checks"]] == ["planned"] * 4
    assert report["release_recommended"] is False


def test_run_remote_wrapup_recommends_release_when_idle():
    runner = WrapupRunner()

    report = run_remote_wrapup(
        RemoteWrapupOptions(host="gpu-box", remote_dir="/root/auto-video/jobs/demo"),
        runner=runner,
    )

    assert report["ok"] is True
    assert report["queue_idle"] is True
    assert report["gpu_idle"] is True
    assert report["release_recommended"] is True
    assert "release" in report["release_message"]
    assert len(runner.commands) == 4


def test_run_remote_wrapup_does_not_recommend_release_when_busy():
    runner = WrapupRunner(busy=True)

    report = run_remote_wrapup(
        RemoteWrapupOptions(host="gpu-box", remote_dir="/root/auto-video/jobs/demo"),
        runner=runner,
    )

    assert report["ok"] is True
    assert report["queue_idle"] is False
    assert report["gpu_idle"] is False
    assert report["release_recommended"] is False
