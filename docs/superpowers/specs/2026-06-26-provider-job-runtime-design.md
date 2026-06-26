# Provider Job Runtime Design

Date: 2026-06-26
Workspace: `/root/auto_ai_vedio`
Phase: 2

## Purpose

Build a provider-neutral job runtime for AI video generation.

The current MVP can initialize projects, validate shots, plan prompts, generate deterministic mock assets, write a manifest, and produce render/probe dry-runs. Phase 2 adds the missing runtime layer between the prompt planner and concrete generation backends:

```text
Project + ShotPlan
  -> Prompt Planner
  -> Job Builder
  -> Job Store / Manifest
  -> Provider Gateway
  -> Provider Result
  -> Manifest + Reports
```

The goal is to support both third-party APIs and rented cloud GPU workers without locking the pipeline to one provider shape.

## Seedance 2.0 Design References

The runtime should borrow Seedance 2.0's workflow strengths at the interface level:

- Multimodal inputs are first-class: text, image, video, and audio references must all survive from `shots.json` into provider requests.
- Short shots remain the main generation unit. The default target range is 4-15 seconds, with validation warnings outside that range rather than hard failure.
- Reference roles are explicit. `first_frame`, `last_frame`, `style_reference`, `motion_reference`, `voice_reference`, and `environment_reference` are provider request fields, not only words inside a prompt.
- Director controls remain structured: `camera_motion`, `environment_motion`, `performance`, `lighting`, `audio_intent`, negative prompt, and subtitle intent.
- Continuity workflows are planned through metadata: bridge shots can later use prior tail frame and next first frame references.
- Audio-video synchronization remains a product goal. Phase 2 transports audio references and audio intent cleanly; it does not train or implement a native joint audio-video model.

Primary references:

- https://seed.bytedance.com/en/seedance2_0
- https://arxiv.org/abs/2604.14148
- Existing MVP design: `docs/superpowers/specs/2026-06-26-ai-video-cli-pipeline-design.md`

## Scope

### In Scope

- Define job models for image, video, and audio generation.
- Create a deterministic job id strategy.
- Convert shots into provider-neutral `GenerationJob` records.
- Add job statuses and status transitions.
- Store job records in `manifest.json` without breaking existing MVP fields.
- Extend mock provider to execute jobs through the same interface real providers will use.
- Add provider health metadata and configuration loading.
- Add CLI commands to plan, submit, and inspect jobs.
- Preserve offline testability with no network, API keys, GPU, or large media.
- Provide a stable target interface for later API and cloud GPU providers.

### Out Of Scope

- Real Seedance API integration.
- Real Wan API integration.
- Cloud VM provisioning.
- Uploading assets to object storage.
- Distributed queue infrastructure.
- Web UI.
- Real billing, quotas, or user accounts.
- Training or fine-tuning a video model.
- Automatic creative strategy generation.

## Success Criteria

The following commands should work against `examples/demo_project`:

```bash
auto-video jobs plan examples/demo_project --provider mock --kind video
auto-video jobs submit examples/demo_project --provider mock --kind video
auto-video jobs status examples/demo_project
auto-video generate examples/demo_project --provider mock
```

The runtime is successful when:

- Dry-run job planning writes no files except optional explicit reports.
- Job submission through `mock` creates deterministic job entries and generated files.
- `manifest.json` records both legacy shot asset fields and the new job records.
- A failed provider result records error, retryability, attempts, and timestamps.
- Default tests stay offline and deterministic.
- Existing MVP commands and tests keep working.

## Concepts

### GenerationJob

A `GenerationJob` represents one provider-executable unit of work.

Fields:

```text
id: stable string
project_name: string
shot_id: string
kind: image | video | audio
provider: string
status: planned | queued | running | succeeded | failed | retryable_failed
prompt: string
negative_prompt: string
duration: float | null
output_path: project-relative path
refs: list[ProviderReference]
controls: ProviderControls
attempts: int
created_at: ISO timestamp
updated_at: ISO timestamp
provider_job_id: string | null
error: string | null
retryable: bool
metadata: object
```

The job id is deterministic:

```text
<project-name>:<shot-id>:<kind>:<provider>
```

This keeps repeated dry-runs stable and makes manifest updates idempotent.

### ProviderReference

A `ProviderReference` is the transport-safe form of `AssetRef`.

Fields:

```text
path: project-relative path
type: image | video | audio | text
role: first_frame | last_frame | style_reference | camera_reference | motion_reference | voice_reference | bgm_reference | environment_reference
usage: preserve_subject | preserve_voice | extract_style | extract_camera_motion | extract_action | extract_audio_rhythm | provide_context
exists: bool
```

The job builder never silently drops references. If a provider cannot use a reference, the provider adapter is responsible for reporting a warning or converting it.

### ProviderControls

`ProviderControls` captures Seedance-inspired director controls without forcing every provider to support every field:

```text
visual_prompt
camera_motion
environment_motion
performance
lighting
audio_intent
subtitle
negative_prompt
aspect_ratio
width
height
fps
```

Provider adapters can flatten controls into prompts or send them as structured request fields.

### ProviderResult

A `ProviderResult` is returned by any provider implementation.

Fields:

```text
job_id
shot_id
kind
provider
status
path
duration
provider_job_id
error
retryable
metadata
```

`ProviderResult` maps back to the existing `AssetResult` behavior so older render/probe code can keep reading `shots.S01.clip`, `shots.S01.image`, and `shots.S01.audio`.

## Status Model

Allowed statuses:

```text
planned
queued
running
succeeded
failed
retryable_failed
```

Rules:

- `planned` is created by dry-run or explicit job planning.
- `queued` is for async providers that accept a remote job but do not complete immediately.
- `running` is used by local or cloud GPU workers while generation is active.
- `succeeded` must include an output path.
- `failed` includes a non-retryable error.
- `retryable_failed` includes an error and `retryable=true`.

The MVP `mock` provider moves directly from `planned` to `succeeded`.

## Manifest Shape

The existing manifest shape remains valid:

```json
{
  "project": "demo_ad",
  "schema_version": "0.1",
  "assets": {},
  "shots": {
    "S01": {
      "status": "generated",
      "provider": "mock",
      "clip": "generated/clips/S01.mp4",
      "duration": 5.0
    }
  },
  "renders": {}
}
```

Phase 2 adds `jobs`:

```json
{
  "jobs": {
    "demo_ad:S01:video:mock": {
      "id": "demo_ad:S01:video:mock",
      "shot_id": "S01",
      "kind": "video",
      "provider": "mock",
      "status": "succeeded",
      "output_path": "generated/clips/S01.mp4",
      "attempts": 1,
      "retryable": false
    }
  }
}
```

The manifest writer must initialize missing `jobs` as `{}`. Existing commands should continue working if `jobs` is absent.

## Provider Configuration

Provider configuration should be loaded from project config first and environment variables second.

Example future shape in `project.yaml`:

```yaml
providers:
  mock:
    mode: local
    timeout_seconds: 30
    max_attempts: 1
  cloud_gpu:
    mode: remote_worker
    endpoint_env: AUTO_VIDEO_CLOUD_GPU_ENDPOINT
    token_env: AUTO_VIDEO_CLOUD_GPU_TOKEN
    timeout_seconds: 1800
    max_attempts: 2
  seedance:
    mode: api
    endpoint_env: AUTO_VIDEO_SEEDANCE_ENDPOINT
    token_env: AUTO_VIDEO_SEEDANCE_TOKEN
    timeout_seconds: 900
    max_attempts: 2
```

Phase 2 only needs to parse and expose this configuration. It should not require any secret to run tests.

## CLI Design

New command group:

```bash
auto-video jobs plan <project> --provider mock --kind video --only S01
auto-video jobs submit <project> --provider mock --kind video --only S01
auto-video jobs status <project>
```

Behavior:

- `jobs plan` prints JSON job records and does not write `manifest.json` unless a later `--write` flag is added.
- `jobs submit` executes jobs through the provider gateway and updates the manifest.
- `jobs status` prints manifest job state grouped by status.
- Existing `images` and `generate` commands should internally use the job builder and provider runtime after migration.

## File Responsibilities

Planned files:

- `src/auto_video/jobs.py`: job dataclasses, status enum strings, conversion helpers.
- `src/auto_video/job_builder.py`: convert `Project` and selected shots into `GenerationJob` records.
- `src/auto_video/job_store.py`: read/write job records inside `manifest.json`.
- `src/auto_video/providers/base.py`: update provider protocol to accept jobs and return provider results.
- `src/auto_video/providers/mock.py`: execute `GenerationJob` while preserving current deterministic output.
- `src/auto_video/pipeline.py`: route existing image/video generation through jobs.
- `src/auto_video/cli.py`: add `jobs` command group.
- `tests/test_jobs.py`: job ids, reference transport, controls, status behavior.
- `tests/test_job_store.py`: manifest compatibility and job persistence.
- `tests/test_job_pipeline.py`: mock job submit updates assets and jobs.
- `tests/test_cli_jobs.py`: command behavior.

## Error Handling

The runtime should use existing user-facing errors:

- `ConfigError` for invalid provider config or unsupported job kind.
- `AssetError` for missing references when validation is required.
- `ProviderError` for provider submission or execution failures.

Provider failures must be recorded in the manifest before returning an error code when possible. This preserves post-failure inspectability.

## Testing Strategy

Tests must follow the existing offline pattern:

- No network calls.
- No API keys.
- No FFmpeg.
- No cloud GPU.
- Deterministic mock file contents.
- TDD for every behavior change.

Required test cases:

- Build a video job from the demo project and preserve prompt, controls, duration, refs, and output path.
- `jobs plan` returns JSON and does not create `manifest.json`.
- `jobs submit --provider mock --kind video` creates `generated/clips/S01.mp4`.
- Manifest contains both `shots.S01.clip` and `jobs.demo_ad:S01:video:mock`.
- Failed provider results record `retryable_failed` and error metadata.
- Existing `generate` command still works and writes legacy shot fields.

## Migration Strategy

Implementation should preserve current behavior while moving internals:

1. Add job models and builder without touching existing pipeline.
2. Add manifest job storage.
3. Update mock provider to support job execution while keeping `generate_video` and `generate_image`.
4. Route `generate_images` and `generate_videos` through jobs.
5. Add CLI `jobs` commands.
6. Keep all existing tests green throughout.

This avoids a risky rewrite and gives real providers a stable target.

## Security And Compliance

The runtime must not store secrets in `manifest.json`, `project.yaml`, or logs. Provider configs should store environment variable names, not token values.

Generated job metadata should avoid direct personal contact data, payment identifiers, or sensitive credential material.

The schema should continue to discourage workflows for unauthorized real-person cloning, protected IP replication, and generated text/logos inside video frames unless the user owns the rights.

## Future Work

After this phase:

- Add an API provider adapter.
- Add a cloud GPU worker adapter with upload/download hooks.
- Add async polling for queued jobs.
- Add retry commands.
- Add provider capability negotiation.
- Add object storage support for large references and outputs.
- Add quality/probe scoring before render assembly.
