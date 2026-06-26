from auto_video.cli import main


def test_cli_help_exits_successfully(capsys):
    code = main(["--help"])
    captured = capsys.readouterr()
    assert code == 0
    assert "auto-video" in captured.out
    assert "validate" in captured.out
