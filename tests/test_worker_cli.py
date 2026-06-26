import json
from pathlib import Path

from auto_video.cli import main


def test_worker_cli_export_run_import(tmp_path: Path, capsys):
    project = tmp_path / "demo"
    bundle = tmp_path / "bundle"
    assert main(["init", str(project)]) == 0

    assert main(["worker", "export", str(project), "--provider", "mock", "--kind", "video", "--out", str(bundle)]) == 0
    assert (bundle / "bundle.json").exists()
    assert not (project / "manifest.json").exists()

    assert main(["worker", "run", str(bundle)]) == 0
    assert (bundle / "result.json").exists()

    assert main(["worker", "import", str(project), str(bundle)]) == 0
    assert (project / "generated" / "clips" / "S01.mp4").exists()
    capsys.readouterr()

    assert main(["jobs", "status", str(project)]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["by_status"]["succeeded"] == 1


def test_worker_cli_export_existing_bundle_requires_force(tmp_path: Path):
    project = tmp_path / "demo"
    bundle = tmp_path / "bundle"
    assert main(["init", str(project)]) == 0
    assert main(["worker", "export", str(project), "--provider", "mock", "--kind", "video", "--out", str(bundle)]) == 0

    assert main(["worker", "export", str(project), "--provider", "mock", "--kind", "video", "--out", str(bundle)]) == 1
    assert main(["worker", "export", str(project), "--provider", "mock", "--kind", "video", "--out", str(bundle), "--force"]) == 0


def test_checked_in_example_worker_export(tmp_path: Path):
    bundle = tmp_path / "example-bundle"

    assert main(["worker", "export", "examples/demo_project", "--provider", "mock", "--kind", "video", "--out", str(bundle)]) == 0

    assert (bundle / "bundle.json").exists()
    assert not (Path("examples/demo_project") / "manifest.json").exists()
