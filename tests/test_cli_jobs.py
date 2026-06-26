import json
from pathlib import Path

from auto_video.cli import main


def test_cli_jobs_plan_does_not_write_manifest(tmp_path: Path, capsys):
    project = tmp_path / "demo"
    assert main(["init", str(project)]) == 0

    assert main(["jobs", "plan", str(project), "--provider", "mock", "--kind", "video"]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["dry_run"] is True
    assert payload["planned"][0]["id"] == "demo_ad:S01:video:mock"
    assert not (project / "manifest.json").exists()


def test_cli_jobs_submit_and_status(tmp_path: Path, capsys):
    project = tmp_path / "demo"
    assert main(["init", str(project)]) == 0

    assert main(["jobs", "submit", str(project), "--provider", "mock", "--kind", "video"]) == 0
    assert (project / "generated" / "clips" / "S01.mp4").exists()
    capsys.readouterr()

    assert main(["jobs", "status", str(project)]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["total"] == 1
    assert payload["by_status"]["succeeded"] == 1
