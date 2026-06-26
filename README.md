# auto_ai_vedio

Seedance-inspired AI video production CLI pipeline.

## MVP Workflow

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m auto_video init demo_project
.venv/bin/python -m auto_video validate demo_project
.venv/bin/python -m auto_video images demo_project --dry-run
.venv/bin/python -m auto_video generate demo_project --dry-run
.venv/bin/python -m auto_video jobs plan demo_project --provider mock --kind video
.venv/bin/python -m auto_video jobs submit demo_project --provider mock --kind video
.venv/bin/python -m auto_video jobs status demo_project
.venv/bin/python -m auto_video worker export demo_project --provider mock --kind video --out /tmp/av-bundle --force
.venv/bin/python -m auto_video worker run /tmp/av-bundle
.venv/bin/python -m auto_video worker import demo_project /tmp/av-bundle
.venv/bin/python -m auto_video remote doctor --host gpu-box --remote-dir /data/auto-video/jobs/demo --dry-run
.venv/bin/python -m auto_video remote run demo_project --provider mock --kind video --host gpu-box --remote-dir /data/auto-video/jobs/demo --local-dir /tmp/av-remote-demo --dry-run
.venv/bin/python -m auto_video generate demo_project --provider mock
.venv/bin/python -m auto_video assemble demo_project --dry-run
.venv/bin/python -m auto_video probe demo_project --dry-run
```

## Design

See `docs/superpowers/specs/2026-06-26-ai-video-cli-pipeline-design.md`.

## Provider Job Runtime

Phase 2 routes generation through provider-neutral jobs:

    .venv/bin/python -m auto_video jobs plan demo_project --provider mock --kind video
    .venv/bin/python -m auto_video jobs submit demo_project --provider mock --kind video
    .venv/bin/python -m auto_video jobs status demo_project

`jobs plan` prints deterministic job records without writing `manifest.json`.
`jobs submit` executes the selected provider and records both legacy shot assets and provider job records in `manifest.json`.
The mock provider stays offline and deterministic, so tests do not need API keys, network, FFmpeg, or cloud GPU access.

## External Command Providers

Phase 6 adds a model-agnostic bridge for real backends such as Wan, ComfyUI, Seedance API wrappers, or custom GPU scripts:

```yaml
default_video_provider: local_wan

providers:
  local_wan:
    mode: external_command
    timeout_seconds: 1800
    command:
      - python
      - scripts/wan_adapter.py
```

`jobs submit --provider local_wan --kind video` writes a Seedance-style job payload, then runs:

    python scripts/wan_adapter.py --job <job-json> --project-root <project-root> --output <output-path>

The adapter reads the JSON payload, translates prompt controls and references into the target model's API, writes the generated asset to `--output`, and exits 0 on success. Non-zero exits and timeouts are recorded as provider job failures in `manifest.json`.

The same provider config works in worker bundles and remote GPU runs when the configured command is available in the worker environment.

## Wan HTTP Adapter

Phase 7 includes `scripts/wan_http_adapter.py` for Wan HTTP services compatible with the old `/root/ai_vedio/tools/providers/wan.py` contract:

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

Run locally through an SSH tunnel:

```bash
ssh -fN -L 8082:127.0.0.1:8082 -p <port> root@<gpu-host>
WAN_BASE_URL=http://127.0.0.1:8082 .venv/bin/python -m auto_video jobs submit demo_project --provider wan_http --kind video
```

The adapter calls `/i2v` when a shot has an existing image reference and `/t2v` otherwise. It maps prompt, negative prompt, duration, width, height, fps, steps, guidance scale, and seed into the Wan request body.

## Cloud Worker Contract

Phase 3 adds a portable worker bundle workflow:

    .venv/bin/python -m auto_video worker export demo_project --provider mock --kind video --out /tmp/av-bundle --force
    .venv/bin/python -m auto_video worker run /tmp/av-bundle
    .venv/bin/python -m auto_video worker import demo_project /tmp/av-bundle

The first worker is local and deterministic. It proves the export/run/import contract without needing a GPU, cloud account, object storage, FFmpeg, or API key. A future cloud transport only needs to move the bundle to a rented GPU machine, run the same worker command, and bring the result bundle back.

## Remote Doctor

Phase 5 adds a remote preflight command for rented GPU machines:

    .venv/bin/python -m auto_video remote doctor --host gpu-box --remote-dir /data/auto-video/jobs/demo --dry-run
    .venv/bin/python -m auto_video remote doctor --host gpu-box --remote-dir /data/auto-video/jobs/demo

`remote doctor --dry-run` prints every planned check without opening SSH or touching the remote machine. A real doctor run checks local `ssh`, local `rsync`, SSH connectivity, remote `rsync`, the remote `auto-video` command, the remote worker CLI, and remote directory writability. It prints a JSON report, exits 0 when every check passes, and exits 1 when one or more checks fail.

`remote doctor` may create the requested remote directory with `mkdir -p`. It does not export bundles, upload assets, run providers, install CUDA, install model weights, or modify local project manifests.

## SSH Remote Worker Transport

Phase 4 adds a thin SSH/rsync transport around worker bundles:

    .venv/bin/python -m auto_video remote run demo_project --provider mock --kind video --host gpu-box --remote-dir /data/auto-video/jobs/demo --local-dir /tmp/av-remote-demo --dry-run

Without `--dry-run`, the command exports a local worker bundle, uploads it with `rsync`, runs `auto-video worker run` over `ssh`, downloads the updated bundle, and imports the result into the local project manifest.

The remote host must already have SSH access, `rsync`, a working `auto-video` command, and any provider runtime or GPU dependencies required by the selected provider. Phase 4 does not create cloud machines or install GPU runtimes.

## Prototype Migration

The old `/root/ai_vedio` project maps into this MVP as follows:

- `batch_plans/*.json` becomes `shots.json`.
- `edl/*.json` becomes render settings plus manifest-derived EDL.
- `tools/providers/*.py` becomes provider adapters.
- `tools/assemble2.py` becomes `src/auto_video/render.py`.
- production SOP documents become validation, probe, and README guidance.

Default tests use the mock provider and do not require API keys, network, cloud GPU, or large video files.
