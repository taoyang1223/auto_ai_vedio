from pathlib import Path

from auto_video.cli import main


def test_cli_help_exits_successfully(capsys):
    code = main(["--help"])
    captured = capsys.readouterr()
    assert code == 0
    assert "auto-video" in captured.out
    assert "validate" in captured.out


def test_cli_init_creates_project(tmp_path: Path):
    project = tmp_path / "demo"
    code = main(["init", str(project)])
    assert code == 0
    assert (project / "project.yaml").exists()
    assert (project / "shots.json").exists()
    assert (project / "assets" / "refs" / "S01.txt").exists()


def test_cli_validate_and_dry_run_generation(tmp_path: Path):
    project = tmp_path / "demo"
    assert main(["init", str(project)]) == 0
    assert main(["validate", str(project)]) == 0
    assert main(["images", str(project), "--dry-run"]) == 0
    assert main(["generate", str(project), "--dry-run"]) == 0
    assert not (project / "manifest.json").exists()


def test_cli_mock_generate_then_probe(tmp_path: Path):
    project = tmp_path / "demo"
    assert main(["init", str(project)]) == 0
    assert main(["generate", str(project), "--provider", "mock"]) == 0
    assert (project / "manifest.json").exists()
    assert main(["probe", str(project), "--dry-run"]) == 0
