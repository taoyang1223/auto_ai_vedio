from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .jobs import ProviderResult
from .providers import get_provider
from .worker_bundle import BUNDLE_SCHEMA_VERSION, load_bundle_index, load_bundle_jobs, provider_result_to_dict


def run_worker_bundle(bundle: Path) -> dict[str, Any]:
    index = load_bundle_index(bundle)
    (bundle / "outputs").mkdir(parents=True, exist_ok=True)
    (bundle / "logs").mkdir(parents=True, exist_ok=True)
    log_path = bundle / "logs" / "worker.log"
    log_lines = ["started worker bundle run"]
    results: list[ProviderResult] = []
    for job in load_bundle_jobs(bundle):
        provider = get_provider(job.provider)
        worker_job = job.__class__(
            **{
                **job.to_dict(),
                "output_path": f"outputs/{job.output_path}",
                "refs": job.refs,
                "controls": job.controls,
            }
        )
        try:
            result = provider.execute_job(worker_job, bundle)
            result = ProviderResult(
                job_id=job.id,
                shot_id=job.shot_id,
                kind=job.kind,
                provider=job.provider,
                status=result.status,
                path=result.path,
                duration=result.duration,
                provider_job_id=result.provider_job_id,
                error=result.error,
                retryable=result.retryable,
                metadata={**result.metadata, "worker": "local"},
            )
        except Exception as exc:
            result = ProviderResult(
                job_id=job.id,
                shot_id=job.shot_id,
                kind=job.kind,
                provider=job.provider,
                status="retryable_failed",
                error=str(exc),
                retryable=True,
                metadata={"worker": "local"},
            )
        results.append(result)
        log_lines.append(f"{job.id} {result.status}")
    payload: dict[str, Any] = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "project": index.get("project"),
        "results": [provider_result_to_dict(result, bundle) for result in results],
    }
    (bundle / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    return payload
