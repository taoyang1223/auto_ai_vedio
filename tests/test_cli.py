from pathlib import Path

from auto_video.cli import main


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


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


def test_cli_init_lists_templates(capsys):
    code = main(["init", "--list-templates"])
    captured = capsys.readouterr()
    assert code == 0
    assert "demo" in captured.out
    assert "autodl_comfyui_wan" in captured.out


def test_cli_init_autodl_comfyui_wan_template(tmp_path: Path):
    project = tmp_path / "wan_project"

    assert main(["init", str(project), "--template", "autodl_comfyui_wan"]) == 0

    assert main(["validate", str(project)]) == 0
    assert (project / "README.md").exists()
    project_yaml = (project / "project.yaml").read_text(encoding="utf-8")
    assert "comfyui_wan" in project_yaml
    assert "wan2_2_smoothmix_i2v" in project_yaml
    assert "prompt_profile:" in project_yaml
    assert "专注的 AI 视频创作者" in project_yaml
    assert "PATH: /opt/auto-ai-video/.venv/bin" in project_yaml
    for shot_id in ("S01", "S02", "S03"):
        assert _png_size(project / "assets" / "refs" / f"{shot_id}_first_frame.png") == (832, 544)


def test_cli_workflows_commands_use_template_registry(tmp_path: Path, capsys):
    project = tmp_path / "wan_project"
    assert main(["init", str(project), "--template", "autodl_comfyui_wan"]) == 0

    assert main(["workflows", "list", str(project)]) == 0
    assert "wan2_2_smoothmix_i2v" in capsys.readouterr().out
    assert main(["workflows", "show", str(project), "wan2_2_smoothmix_i2v"]) == 0
    assert "SmoothMix" in capsys.readouterr().out
    assert main(["workflows", "env", str(project), "wan2_2_smoothmix_i2v"]) == 0
    assert "COMFYUI_WORKFLOW_PROFILE=wan2_2_smoothmix_i2v" in capsys.readouterr().out


def test_cli_init_rejects_overwrite_without_force(tmp_path: Path):
    project = tmp_path / "demo"

    assert main(["init", str(project)]) == 0
    assert main(["init", str(project)]) == 1
    assert main(["init", str(project), "--force"]) == 0


def test_cli_init_rejects_unknown_template(tmp_path: Path):
    assert main(["init", str(tmp_path / "bad"), "--template", "missing"]) == 1


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


def test_cli_probe_strict_fails_when_clips_are_missing(tmp_path: Path):
    project = tmp_path / "demo"
    assert main(["init", str(project)]) == 0
    assert main(["probe", str(project), "--strict"]) == 1


def test_checked_in_example_validates():
    assert main(["validate", "examples/demo_project"]) == 0
    assert main(["images", "examples/demo_project", "--dry-run"]) == 0
    assert main(["generate", "examples/demo_project", "--dry-run"]) == 0
