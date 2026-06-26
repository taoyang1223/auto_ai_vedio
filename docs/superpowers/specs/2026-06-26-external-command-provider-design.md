# External Command Provider Design

Date: 2026-06-26
Workspace: `/root/auto_ai_vedio`
Phase: 6

## Purpose

Add the first real-model integration boundary after remote execution.

Phases 1 through 5 can plan jobs, export worker bundles, run them remotely through SSH/rsync, and preflight rented GPU hosts. The worker still only has a deterministic mock provider. Phase 6 adds an `external_command` provider mode so a project can delegate generation to any local or remote script that follows a small command-line contract.

This lets the pipeline call Wan, ComfyUI, Seedance API wrappers, or future model servers without hardcoding one vendor into the core package.

## Seedance-Inspired Requirements

Seedance 2.0 is strong because the model interface carries more than a raw prompt:

- multimodal references with explicit roles
- first/last frame anchoring
- camera and motion intent
- subject/performance continuity
- negative prompts and quality constraints
- duration, aspect ratio, resolution, and fps
- audio intent and subtitle intent

Phase 6 preserves these signals in the external job payload. The core system does not need to know how Wan, ComfyUI, or Seedance consume the signals; wrappers can translate the shared payload into model-specific requests.

## CLI Workflow

Project config:

```yaml
default_video_provider: local_wan

providers:
  local_wan:
    mode: external_command
    command:
      - python
      - scripts/wan_adapter.py
    timeout_seconds: 1800
```

Run locally:

```bash
auto-video jobs submit demo_project --provider local_wan --kind video
```

Run on rented GPU:

```bash
auto-video remote doctor --host gpu-box --remote-dir /data/auto-video/jobs/demo
auto-video remote run demo_project --provider local_wan --kind video --host gpu-box --remote-dir /data/auto-video/jobs/demo
```

The same worker bundle contract from Phase 3 and remote transport from Phase 4 should work. The remote machine only needs the project package, the adapter script, and model runtime installed.

## Provider Contract

For each generation job, the provider writes a JSON payload and invokes:

```bash
<configured command...> \
  --job <job-json> \
  --project-root <project-root> \
  --output <absolute-output-path>
```

The adapter must:

- read `<job-json>`
- generate the requested asset
- write the asset to `--output`
- exit 0 on success
- exit non-zero on failure

The adapter may print logs to stdout/stderr. The core provider stores short snippets in manifest metadata for troubleshooting.

## Job Payload

The payload should include:

```json
{
  "job": {
    "id": "demo_ad:S01:video:local_wan",
    "kind": "video",
    "prompt": "...",
    "negative_prompt": "...",
    "duration": 5.0,
    "output_path": "generated/clips/S01.mp4",
    "refs": [],
    "controls": {}
  },
  "project_root": "/tmp/bundle/project",
  "output_path": "/tmp/bundle/project/generated/clips/S01.mp4",
  "references": [
    {
      "path": "assets/refs/S01.png",
      "absolute_path": "/tmp/bundle/project/assets/refs/S01.png",
      "type": "image",
      "role": "first_frame",
      "usage": "preserve_subject",
      "exists": true
    }
  ]
}
```

The payload intentionally avoids environment variable values and tokens.

## Configuration

Provider config uses the existing `ProviderConfig`:

- `mode: external_command`
- `command`: required list of command tokens
- `timeout_seconds`: passed to subprocess timeout
- `max_attempts`: parsed but not retried in Phase 6
- `endpoint_env` and `token_env`: preserved for wrappers but not expanded into payload
- all other keys stay in `options`

Provider names should be project-defined. A project may use `local_wan`, `comfy_i2v`, `seedance_api`, or other names as long as the provider config declares `mode: external_command`.

## Safety

- Commands run with `subprocess.run([...], shell=False)`.
- `command` must be a non-empty list of strings.
- Command tokens cannot contain NUL or newline/control characters.
- Job JSON is written under `<project-root>/.auto-video/provider-jobs/`.
- Output path is resolved from `GenerationJob.output_path` under the project root.
- A successful command must create the expected output file.
- Secrets are not printed or copied into job JSON.

## File Responsibilities

Create:

- `src/auto_video/providers/external_command.py`
  - `ExternalCommandProvider`
  - job payload construction
  - safe command validation
  - subprocess execution
  - `ProviderResult` mapping

Modify:

- `src/auto_video/providers/__init__.py`
  - return mock provider for `mock`
  - return external provider when project config mode is `external_command`

- `src/auto_video/pipeline.py`
  - pass provider config into provider registry

- `src/auto_video/models.py`
  - allow project-defined provider names in defaults and shots

- `README.md`
  - document external command provider workflow

Tests:

- `tests/test_external_command_provider.py`
  - command success writes output and result metadata
  - command failure records failed result
  - timeout records retryable failed result
  - unsafe command config is rejected
  - job payload includes Seedance-style controls and resolved references

- Existing provider/job/worker/remote tests must keep passing.

## Out Of Scope

- Built-in Wan HTTP client.
- Built-in Seedance API client.
- ComfyUI workflow generation.
- Retry scheduling.
- GPU provisioning.
- Model installation.
- Streaming logs.

Those become small wrappers once this command contract exists.

## Success Criteria

Phase 6 is complete when a test project can configure a fake external command and:

```bash
auto-video jobs submit demo_project --provider local_wan --kind video
```

writes `generated/clips/S01.mp4`, records a succeeded provider job, and preserves prompt, controls, references, stdout/stderr snippets, and output metadata.

The same provider must also work inside worker bundles because remote GPU execution uses `auto-video worker run`.
