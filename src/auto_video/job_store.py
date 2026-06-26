from __future__ import annotations

from pathlib import Path
from typing import Any

from .jobs import GenerationJob, ProviderResult, utc_now_iso
from .manifest import ManifestStore


class JobStore:
    def __init__(self, path: Path, *, project_name: str):
        self.manifest = ManifestStore(path, project_name=project_name)
        self.manifest.data.setdefault("jobs", {})

    @property
    def data(self) -> dict[str, Any]:
        return self.manifest.data

    def record_job(self, job: GenerationJob) -> None:
        self.data["jobs"][job.id] = job.to_dict()

    def record_result(self, result: ProviderResult) -> None:
        now = utc_now_iso()
        job = self.data["jobs"].setdefault(
            result.job_id,
            {
                "id": result.job_id,
                "shot_id": result.shot_id,
                "kind": result.kind,
                "provider": result.provider,
                "attempts": 0,
                "created_at": now,
                "metadata": {},
            },
        )
        job["status"] = result.status
        job["updated_at"] = now
        job["attempts"] = int(job.get("attempts", 0)) + 1
        job["retryable"] = result.retryable
        job["provider_job_id"] = result.provider_job_id
        job["error"] = result.error
        job["metadata"] = result.metadata
        if result.path is not None:
            job["output_path"] = self.manifest._relative(result.path)
        if result.duration is not None:
            job["duration"] = result.duration
        if result.status == "succeeded":
            self.manifest.record_asset(result.to_asset_result())
        elif result.status in {"failed", "retryable_failed"}:
            shot = self.data["shots"].setdefault(result.shot_id, {})
            shot["status"] = "failed"
            shot["provider"] = result.provider
            if result.error:
                shot["error"] = result.error
            if result.retryable:
                shot["retryable"] = True

    def jobs(self) -> dict[str, dict[str, Any]]:
        return self.data.get("jobs", {})

    def summary(self) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        for job in self.jobs().values():
            status = str(job.get("status", "unknown"))
            by_status[status] = by_status.get(status, 0) + 1
        return {"total": len(self.jobs()), "by_status": by_status, "jobs": self.jobs()}

    def save(self) -> None:
        self.manifest.save()
