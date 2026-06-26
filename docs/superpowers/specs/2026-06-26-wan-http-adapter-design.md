# Wan HTTP Adapter Design

Date: 2026-06-26
Workspace: `/root/auto_ai_vedio`
Phase: 7

## Purpose

Add the first concrete real-model adapter on top of Phase 6 `external_command`.

The old `/root/ai_vedio/tools/providers/wan.py` client targets a synchronous Wan HTTP service:

- `GET /health`
- `POST /i2v` with `image_base64`, prompt controls, and render settings
- `POST /t2v` with prompt controls and render settings

Phase 7 turns that knowledge into a standalone adapter script that can be used locally or on a rented GPU machine through `auto-video remote run`.

## Workflow

Configure a project:

```yaml
default_video_provider: wan_http

providers:
  wan_http:
    mode: external_command
    timeout_seconds: 1800
    command:
      - python
      - scripts/wan_http_adapter.py
      - --base-url-env
      - WAN_BASE_URL
      - --token-env
      - WAN_TOKEN
```

Run locally:

```bash
WAN_BASE_URL=http://127.0.0.1:8082 auto-video jobs submit demo_project --provider wan_http --kind video
```

Run on a remote GPU host:

```bash
auto-video remote doctor --host gpu-box --remote-dir /data/auto-video/jobs/demo
auto-video remote run demo_project --provider wan_http --kind video --host gpu-box --remote-dir /data/auto-video/jobs/demo
```

## Adapter Contract

The adapter implements the Phase 6 command contract:

```bash
python scripts/wan_http_adapter.py \
  --base-url-env WAN_BASE_URL \
  --job <job-json> \
  --project-root <project-root> \
  --output <output-mp4>
```

It reads the Phase 6 payload, translates it into Wan service JSON, posts to the Wan server, and writes the returned video bytes to `--output`.

## Request Mapping

Common fields:

- `prompt`: `payload.job.prompt`
- `negative_prompt`: `payload.job.negative_prompt` or Wan default negative prompt
- `width`: `payload.job.controls.width`
- `height`: `payload.job.controls.height`
- `fps`: `payload.job.controls.fps`
- `num_frames`: explicit `--frames` or `round(duration * fps)`
- `num_inference_steps`: `--steps`, default 24
- `guidance_scale`: `--guidance-scale`, default 5.0
- `seed`: `--seed`, default 42

If the payload contains an existing image reference, the adapter calls `/i2v` and includes `image_base64`.

If no image reference exists, the adapter calls `/t2v`.

## Safety

- No API token is written into job JSON.
- Token is read from an environment variable named by `--token-env`.
- Base URL can be passed through `--base-url` or `--base-url-env`.
- Output is created only at the `--output` path given by the provider.
- The script uses Python standard library networking; no runtime dependency is added to the package.

## Tests

Default tests use a local in-process HTTP server and do not require Wan, GPU, internet, or credentials.

Tests should cover:

- I2V request with base64 image reference.
- T2V request when no image reference exists.
- Environment-based base URL and token header.
- JSON error response returns non-zero and does not create output.
- Integration with `external_command` provider using the adapter script.

## Out Of Scope

- Starting the Wan server.
- Installing Wan model weights.
- Creating SSH tunnels.
- ComfyUI workflow support.
- Async queue support.

Those are later platform/runtime tasks.
