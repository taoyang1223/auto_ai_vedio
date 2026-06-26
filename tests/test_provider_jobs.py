from auto_video.job_builder import build_jobs
from auto_video.project import load_project
from auto_video.providers.mock import MockProvider


def test_mock_provider_executes_video_job(demo_project_files):
    project = load_project(demo_project_files)
    job = build_jobs(project, kind="video", provider_name="mock")[0]
    provider = MockProvider()

    result = provider.execute_job(job, project.config.root)

    assert result.job_id == "demo_ad:S01:video:mock"
    assert result.status == "succeeded"
    assert result.path == demo_project_files / "generated" / "clips" / "S01.mp4"
    assert result.duration == 5.0
    assert result.path.read_text(encoding="utf-8").startswith("mock video")


def test_mock_provider_executes_image_job(demo_project_files):
    project = load_project(demo_project_files)
    job = build_jobs(project, kind="image", provider_name="mock")[0]
    provider = MockProvider()

    result = provider.execute_job(job, project.config.root)

    assert result.job_id == "demo_ad:S01:image:mock"
    assert result.status == "succeeded"
    assert result.path == demo_project_files / "generated" / "images" / "S01.txt"
    assert result.path.read_text(encoding="utf-8").startswith("mock image")
