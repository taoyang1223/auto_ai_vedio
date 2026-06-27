import pytest

from auto_video.errors import ConfigError
from auto_video.job_builder import build_jobs
from auto_video.job_selection import select_jobs
from auto_video.project import load_project


def test_select_jobs_failed_only_uses_job_status(demo_project_files):
    project = load_project(demo_project_files)
    job = build_jobs(project, kind="video", provider_name="mock")[0]

    selected = select_jobs(
        [job],
        {"jobs": {job.id: {"status": "retryable_failed"}}},
        failed_only=True,
    )

    assert selected == [job]


def test_select_jobs_skip_succeeded_uses_job_status(demo_project_files):
    project = load_project(demo_project_files)
    job = build_jobs(project, kind="video", provider_name="mock")[0]

    selected = select_jobs(
        [job],
        {"jobs": {job.id: {"status": "succeeded"}}},
        skip_succeeded=True,
    )

    assert selected == []


def test_select_jobs_uses_legacy_shot_status_when_job_missing(demo_project_files):
    project = load_project(demo_project_files)
    job = build_jobs(project, kind="video", provider_name="mock")[0]

    selected = select_jobs(
        [job],
        {"shots": {"S01": {"status": "generated", "clip": "generated/clips/S01.mp4"}}},
        skip_succeeded=True,
    )

    assert selected == []


def test_select_jobs_rejects_conflicting_modes(demo_project_files):
    project = load_project(demo_project_files)
    job = build_jobs(project, kind="video", provider_name="mock")[0]

    with pytest.raises(ConfigError) as exc:
        select_jobs([job], {}, failed_only=True, skip_succeeded=True)

    assert "cannot be used together" in str(exc.value)
