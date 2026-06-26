# Cloud Worker Contract Design

Date: 2026-06-26
Workspace: `/root/auto_ai_vedio`
Phase: 3

## Purpose

Build a cloud-worker contract for AI video generation jobs.

Phase 2 added provider-neutral `GenerationJob` records, a `JobStore`, mock provider execution, and `auto-video jobs plan|submit|status`. Phase 3 adds a portable worker boundary so jobs can be exported from a project, executed in another environment, and imported back into the source project.

The first implementation is local and deterministic. It proves the bundle format, worker execution behavior, output layout, result import, and error reporting without requiring a rented GPU, network, API keys, FFmpeg, or object storage.

## Design Goal

Support this workflow:

```bash
auto-video worker export demo_project --provider mock --kind video --out /tmp/job-bundle
auto-video worker run /tmp/job-bundle
auto-video worker import demo_project /tmp/job-bundle
auto-video jobs status demo_project
```

This maps directly to a future cloud workflow:

```text
local project -> export bundle -> upload bundle -> remote worker run -> download result -> import result
```

The transport can later be SCP, rsync, HTTP, object storage, or a cloud-specific API. The contract does not depend on a specific cloud vendor.

## In Scope

- Define a worker bundle directory format.
- Export selected `GenerationJob` records and reference assets into a bundle.
- Run a bundle with the existing provider gateway.
- Write `result.json`, `outputs/`, and `logs/` inside the bundle.
- Import worker results back into the source project.
- Update `manifest.json` with both job records and legacy shot asset fields.
- Add CLI commands:
  - `auto-video worker export`
  - `auto-video worker run`
  - `auto-video worker import`
- Preserve offline deterministic tests.
- Keep existing `jobs` and `generate` commands working.

## Out Of Scope

- Real cloud VM provisioning.
- SSH/SCP/rsync transport.
- Object storage.
- Distributed queues.
- Async polling.
- Real Seedance, Wan, or other remote APIs.
- GPU runtime installation.
- Docker image building.
- Payment, quota, or account management.

## Worker Bundle Layout

An exported bundle is a directory:

```text
job-bundle/
  bundle.json
  project.yaml
  shots.json
  jobs/
    demo_ad_S01_video_mock.json
  refs/
    S01/
      assets_refs_S01.txt
  outputs/
  logs/
```

### `bundle.json`

`bundle.json` is the bundle index:

```json
{
  "schema_version": "0.1",
  "project": "demo_ad",
  "created_at": "2026-06-26T00:00:00Z",
  "source_root": "/root/auto_ai_vedio/examples/demo_project",
  "jobs": [
    "jobs/demo_ad_S01_video_mock.json"
  ],
  "refs": [
    {
      "job_id": "demo_ad:S01:video:mock",
      "source": "assets/refs/S01.txt",
      "bundle_path": "refs/S01/assets_refs_S01.txt",
      "role": "first_frame",
      "usage": "preserve_subject"
    }
  ],
  "results": []
}
```

The source root is informational. Worker execution must not require access to the original project path.

### Job Files

Each file in `jobs/` stores one `GenerationJob.to_dict()` payload. Job ids contain colons, so filenames use a sanitized id:

```text
demo_ad:S01:video:mock -> demo_ad_S01_video_mock.json
```

The job's `output_path` remains project-relative, such as:

```text
generated/clips/S01.mp4
```

During worker execution, the output is written under the bundle:

```text
outputs/generated/clips/S01.mp4
```

### Reference Assets

Reference assets are copied into `refs/<shot-id>/`. The bundle keeps the original project-relative path in metadata and uses a safe filename inside the bundle.

Rules:

- Existing references are copied.
- Missing references are recorded with `"missing": true`.
- Export does not fail for missing refs if project validation already permits the shot.
- The worker receives the same `GenerationJob.refs` metadata, plus bundle metadata in `bundle.json`.

## Worker Execution

`auto-video worker run <bundle-dir>` reads `bundle.json`, loads each job file, and executes jobs through the normal provider gateway.

For Phase 3:

- `mock` is the only required worker provider.
- The worker writes deterministic output files under `outputs/`.
- The worker writes one `result.json` file:

```json
{
  "schema_version": "0.1",
  "project": "demo_ad",
  "results": [
    {
      "job_id": "demo_ad:S01:video:mock",
      "shot_id": "S01",
      "kind": "video",
      "provider": "mock",
      "status": "succeeded",
      "path": "outputs/generated/clips/S01.mp4",
      "duration": 5.0,
      "retryable": false,
      "error": null,
      "metadata": {
        "worker": "local",
        "mock": true
      }
    }
  ]
}
```

The worker also writes a simple text log:

```text
logs/worker.log
```

If a provider fails, the worker writes `status: retryable_failed` or `status: failed` and records the error. It should still write `result.json` whenever possible.

## Import Behavior

`auto-video worker import <project> <bundle-dir>` reads `result.json`, copies successful outputs from the bundle back into the project root, and records each result in `JobStore`.

Example copy:

```text
bundle outputs/generated/clips/S01.mp4
  -> project generated/clips/S01.mp4
```

The import then updates:

```text
manifest.json jobs.demo_ad:S01:video:mock
manifest.json shots.S01.clip
```

Failed results are imported into the manifest as inspectable job failures. They do not create legacy `clip`, `image`, or `audio` fields.

## CLI Design

New command group:

```bash
auto-video worker export <project> --provider mock --kind video --out <bundle-dir> [--only S01,S03] [--force]
auto-video worker run <bundle-dir>
auto-video worker import <project> <bundle-dir>
```

Behavior:

- `worker export` creates the target bundle directory.
- `worker export` rejects an existing non-empty target directory unless `--force` is passed.
- `worker export --force` replaces only the target bundle directory, never the source project.
- `worker export` does not create or modify the project manifest.
- `worker run` does not need the source project directory.
- `worker run` writes results inside the bundle only.
- `worker import` is the only command that writes generated outputs back into the project.
- Existing `jobs submit` remains the simple local path and does not require worker bundles.

## File Responsibilities

Planned files:

- `src/auto_video/worker_bundle.py`: bundle paths, export, load, result serialization, import helpers.
- `src/auto_video/worker_runner.py`: execute bundle jobs through provider gateway.
- `src/auto_video/cli.py`: add `worker export|run|import`.
- `tests/test_worker_bundle.py`: export layout, reference copying, result import.
- `tests/test_worker_cli.py`: CLI behavior.
- `README.md`: document local worker workflow.

Existing files that are reused:

- `src/auto_video/jobs.py`
- `src/auto_video/job_builder.py`
- `src/auto_video/job_store.py`
- `src/auto_video/providers/mock.py`

## Data Flow

```text
Project root
  -> load_project()
  -> build_jobs()
  -> export_worker_bundle()
  -> bundle directory
  -> run_worker_bundle()
  -> result.json + outputs/
  -> import_worker_results()
  -> project generated files + manifest.json
```

This separates planning, execution, and import. That separation is what lets future cloud transports be added without changing provider/job semantics.

## Error Handling

Use existing user-facing errors:

- `ConfigError` for malformed bundles or unsupported job kinds.
- `AssetError` for unsafe bundle paths or missing required files during import.
- `ProviderError` for worker execution failures.

Path safety rules:

- Bundle import must not write outside the project root.
- Worker run must not write outside the bundle root.
- Job output paths are always interpreted as relative paths.
- Absolute output paths in bundle job files are rejected.
- `..` path traversal in bundle job files is rejected.

## Testing Strategy

Default tests remain offline and deterministic:

- No network.
- No GPU.
- No cloud account.
- No FFmpeg.
- No object storage.
- No real API key.

Required test cases:

- Exporting a demo project creates `bundle.json`, job JSON, copied refs, `outputs/`, and `logs/`.
- Exporting does not create `manifest.json` in the source project.
- Worker run reads a bundle and writes mock output plus `result.json`.
- Worker run does not require the source project path to exist.
- Import copies output back into the project and updates `manifest.json`.
- Import records failed results without creating legacy asset fields.
- CLI worker workflow runs end to end in a temp directory.
- Existing `jobs submit` and `generate` tests still pass.

## Future Cloud Transport

After this phase, a cloud transport can be added as a thin layer:

```text
export bundle
upload bundle
remote: auto-video worker run bundle
download bundle/result
import bundle
```

Possible transports:

- `scp` or `rsync` to a rented GPU box.
- Object storage upload/download.
- Provider-specific runpod/vast/autodl wrapper.
- HTTP worker service.

The transport layer should not know how to build prompts, execute providers, or write manifests. It only moves bundles and starts worker commands.

## Security

- Bundles must not include API tokens.
- Provider config may include environment variable names but not secret values.
- Import must reject unsafe output paths.
- Logs should not print secrets from environment variables.
- Bundle metadata can include source paths for debugging, but workers must not rely on them.

## Success Criteria

Phase 3 is complete when:

```bash
auto-video worker export demo_project --provider mock --kind video --out /tmp/av-bundle
auto-video worker run /tmp/av-bundle
auto-video worker import demo_project /tmp/av-bundle
auto-video jobs status demo_project
```

works locally, creates generated mock video output, and updates `manifest.json` with both job records and legacy shot asset fields.

All existing tests from Phase 2 must continue passing.
