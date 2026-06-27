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
.venv/bin/python -m auto_video assemble demo_project
.venv/bin/python -m auto_video probe demo_project --dry-run
```

## Project Templates

`init` can scaffold either the small offline demo or a real AutoDL ComfyUI Wan starter:

```bash
.venv/bin/python -m auto_video init --list-templates
.venv/bin/python -m auto_video init demo_project --template demo
.venv/bin/python -m auto_video init wan_story --template autodl_comfyui_wan
```

The `autodl_comfyui_wan` template creates a three-shot image-to-video project with:

- `comfyui_wan` external-command provider config.
- A `wan2_2_smoothmix_i2v` ComfyUI workflow registry entry with node mappings.
- An `autodl_5090` remote profile ready for host, port, and workflow path edits.
- Placeholder first-frame PNGs under `assets/refs/`.
- A project-local README with the validate, remote run, assemble, and wrap-up commands.

Before running it on a rented GPU, replace the placeholder PNGs with real first-frame images, edit `remote_profiles.autodl_5090` in `project.yaml`, then run:

```bash
.venv/bin/python -m auto_video validate wan_story
.venv/bin/python -m auto_video remote run wan_story --profile autodl_5090 --provider comfyui_wan --kind video
.venv/bin/python -m auto_video probe wan_story --strict
.venv/bin/python -m auto_video continuity extract-tail-frames wan_story
.venv/bin/python -m auto_video assemble wan_story
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

`assemble --dry-run` validates clip readiness and prints the concat-based ffmpeg command. `assemble` writes `renders/final.mp4`, records `renders.final` in `manifest.json`, and fails early if a referenced clip is missing or empty.

`probe` performs media-quality checks after generation. In normal mode it reports per-shot `ok`, `warning`, and `failed` checks for clip existence, video stream readability, resolution, duration, and fps. With `--strict`, the command exits 1 when any shot fails, making it suitable as a batch gate before continuity extraction and final assembly:

```bash
.venv/bin/python -m auto_video probe demo_project --strict
.venv/bin/python -m auto_video probe demo_project --strict --blackdetect
```

`--blackdetect` also runs ffmpeg black-frame detection and flags clips that are almost entirely black. It is optional because it is slower than ffprobe-only checks.

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

Phase 7 includes a Wan HTTP adapter for services compatible with the old `/root/ai_vedio/tools/providers/wan.py` contract:

```yaml
default_video_provider: wan_http

providers:
  wan_http:
    mode: external_command
    timeout_seconds: 1800
    command:
      - python
      - -m
      - auto_video.wan_http_adapter
      - --base-url-env
      - WAN_BASE_URL
      - --token-env
      - WAN_TOKEN
```

Run locally through an SSH tunnel:

```bash
ssh -fN -L 8082:127.0.0.1:8082 -p <port> root@<gpu-host>
WAN_BASE_URL=http://127.0.0.1:8082 python -m auto_video.wan_runtime_doctor --base-url-env WAN_BASE_URL --require-i2v
WAN_BASE_URL=http://127.0.0.1:8082 .venv/bin/python -m auto_video jobs submit demo_project --provider wan_http --kind video
```

The adapter calls `/i2v` when a shot has an existing image reference and `/t2v` otherwise. It maps prompt, negative prompt, duration, width, height, fps, steps, guidance scale, and seed into the Wan request body.

Phase 8 adds `auto_video.wan_runtime_doctor` for checking the Wan service before generation:

```bash
python -m auto_video.wan_runtime_doctor --base-url http://127.0.0.1:8082 --require-i2v --require-t2v
```

It only calls `GET /health`, prints JSON, and exits 1 if the service is unreachable or the required I2V/T2V model is not loaded.

Phase 9 adds remote Wan smoke planning and remote worker environment injection:

```bash
python scripts/wan_remote_smoke.py \
  --project demo_project \
  --host gpu-box \
  --remote-dir /data/auto-video/jobs/demo \
  --wan-base-url http://127.0.0.1:8082 \
  --require-i2v
```

The command prints the planned `remote doctor`, remote Wan runtime doctor, and `remote run` commands by default. Add `--execute` to run them in order. `remote run` also supports repeatable `--remote-env NAME=value`, which is how `WAN_BASE_URL` reaches the remote worker:

The remote Wan doctor now defaults to `python -m auto_video.wan_runtime_doctor`, so the installed `auto-video` package is enough on the GPU host. If you need to use a standalone script instead, pass `--remote-wan-doctor /absolute/path/to/wan_runtime_doctor.py`.

```bash
.venv/bin/python -m auto_video remote run demo_project --provider wan_http --kind video \
  --host gpu-box \
  --remote-dir /data/auto-video/jobs/demo \
  --remote-env WAN_BASE_URL=http://127.0.0.1:8082
```

## Rented GPU Wan Runbook

Phase 11 adds a runbook planner for the real cloud GPU workflow. It does not rent machines or run SSH commands; it prints the copyable install, preflight, generation, and shutdown steps:

```bash
.venv/bin/python -m auto_video.wan_gpu_runbook \
  --project demo_project \
  --host gpu-box \
  --remote-dir /data/auto-video/jobs/demo \
  --format markdown
```

By default the runbook installs this repo into `/opt/auto-ai-video/.venv` on the GPU host, uses `/opt/auto-ai-video/.venv/bin/auto-video` for remote worker checks, and points the remote worker at `WAN_BASE_URL=http://127.0.0.1:8082`. This follows the old project lesson: put the job on the GPU host and let it call the local Wan HTTP service instead of depending on a fragile long-lived SSH tunnel.

If your Wan server has a known launch command, include it in the plan:

```bash
.venv/bin/python -m auto_video.wan_gpu_runbook \
  --project demo_project \
  --host gpu-box \
  --remote-dir /data/auto-video/jobs/demo \
  --wan-start-command 'nohup /root/miniconda3/bin/python3 /root/wan_server.py --mode i2v --offload none --port 8082 > /tmp/wan_server.log 2>&1 &' \
  --format markdown
```

After reviewing the runbook, run the preflight commands first, then the generated `remote_run` command. Shut down or release the GPU machine after outputs are imported locally.

## AutoDL ComfyUI Wan Adapter

Phase 12 adds a ComfyUI adapter for AutoDL Wan2.2 workflow images such as `wan2.2视频带工作流`. On the tested instance, ComfyUI runs on the GPU host at `http://127.0.0.1:6006`, and the useful image-to-video workflow is:

```text
/root/zealman-app/workflows/G10-图生视频-Wan2.2SmoothMixV2.json
```

Run a ComfyUI runtime preflight on the GPU host before spending time on generation:

```bash
COMFYUI_BASE_URL=http://127.0.0.1:6006 \
COMFYUI_WORKFLOW=/root/zealman-app/workflows/G10-图生视频-Wan2.2SmoothMixV2.json \
/opt/auto-ai-video/.venv/bin/python -m auto_video.comfyui_runtime_doctor \
  --base-url-env COMFYUI_BASE_URL \
  --workflow-env COMFYUI_WORKFLOW \
  --require-gpu \
  --require-idle
```

From your local machine, run the same preflight through SSH:

```bash
ssh -p <port> root@<autodl-host> \
  'COMFYUI_BASE_URL=http://127.0.0.1:6006 COMFYUI_WORKFLOW=/root/zealman-app/workflows/G10-图生视频-Wan2.2SmoothMixV2.json /opt/auto-ai-video/.venv/bin/python -m auto_video.comfyui_runtime_doctor --base-url-env COMFYUI_BASE_URL --workflow-env COMFYUI_WORKFLOW --require-gpu --require-idle'
```

Provider config:

```yaml
default_video_provider: comfyui_wan

providers:
  comfyui_wan:
    mode: external_command
    timeout_seconds: 3600
    command:
      - python
      - -m
      - auto_video.comfyui_wan_adapter
      - --base-url-env
      - COMFYUI_BASE_URL
      - --workflow-env
      - COMFYUI_WORKFLOW
      - --workflow-profile-env
      - COMFYUI_WORKFLOW_PROFILE
```

Phase 22 adds a ComfyUI workflow registry so the stable workflow exported from the ComfyUI WebUI can be tracked with its node IDs, model notes, and recommended runtime settings:

```yaml
comfyui_workflows:
  wan2_2_smoothmix_i2v:
    title: Wan2.2 SmoothMix image-to-video
    provider: comfyui_wan
    kind: image_to_video
    base_url: http://127.0.0.1:6006
    base_url_env: COMFYUI_BASE_URL
    workflow_env: COMFYUI_WORKFLOW
    workflow_path: /root/zealman-app/workflows/G10-图生视频-Wan2.2SmoothMixV2.json
    profile_env: COMFYUI_WORKFLOW_PROFILE
    parameters:
      seed: 42
      steps: 20
    nodes:
      prompt:
        id: "257"
        input: value
      negative:
        id: "218"
        input: text
      image:
        id: "224"
        input: image
```

List or inspect registered workflows:

```bash
.venv/bin/python -m auto_video workflows list demo_project
.venv/bin/python -m auto_video workflows show demo_project wan2_2_smoothmix_i2v
.venv/bin/python -m auto_video workflows env demo_project wan2_2_smoothmix_i2v
```

ComfyUI remains the workflow editor and debugging console. `auto-video` uses the registry plus the ComfyUI API for repeatable batch runs, so the final production path does not depend on manually clicking Run in the node UI.

Remote run example:

```bash
.venv/bin/python -m auto_video remote run demo_project --provider comfyui_wan --kind video \
  --host gpu-box \
  --remote-dir /data/auto-video/jobs/demo \
  --remote-auto-video /opt/auto-ai-video/.venv/bin/auto-video \
  --remote-env COMFYUI_BASE_URL=http://127.0.0.1:6006 \
  --remote-env 'COMFYUI_WORKFLOW=/root/zealman-app/workflows/G10-图生视频-Wan2.2SmoothMixV2.json'
```

For repeated AutoDL runs, put the remote settings in `project.yaml`:

```yaml
remote_profiles:
  autodl_5090:
    host: root@<autodl-host>
    remote_dir: /root/auto-video/jobs/demo
    remote_auto_video: /opt/auto-ai-video/.venv/bin/auto-video
    ssh_options:
      - Port=<ssh-port>
    remote_env:
      COMFYUI_BASE_URL: http://127.0.0.1:6006
      COMFYUI_WORKFLOW: /root/zealman-app/workflows/G10-图生视频-Wan2.2SmoothMixV2.json
      COMFYUI_WORKFLOW_PROFILE: wan2_2_smoothmix_i2v
```

Then list and use the profile:

```bash
.venv/bin/python -m auto_video remote profiles demo_project
.venv/bin/python -m auto_video remote run demo_project --profile autodl_5090 --provider comfyui_wan --kind video
```

For batch projects, omit `--only` to run every shot in `shots.json`. Use selection flags when resuming work:

```bash
# Plan only jobs that previously failed or were retryable failures.
.venv/bin/python -m auto_video jobs plan demo_project --provider comfyui_wan --kind video --failed-only

# Remote-run only failed jobs on the configured AutoDL profile.
.venv/bin/python -m auto_video remote run demo_project --profile autodl_5090 --provider comfyui_wan --kind video --failed-only

# Continue a batch while skipping jobs already marked succeeded in manifest.json.
.venv/bin/python -m auto_video remote run demo_project --profile autodl_5090 --provider comfyui_wan --kind video --skip-succeeded
```

After clips are generated, extract tail frames for continuity between adjacent shots:

```bash
.venv/bin/python -m auto_video continuity extract-tail-frames demo_project --dry-run
.venv/bin/python -m auto_video continuity extract-tail-frames demo_project
```

The command reads generated clips from `manifest.json`, writes tail frames under `assets/continuity/`, and records `continuity_refs` on the next shot. Future job payloads then include the previous shot's tail frame before static shot refs, which lets image-to-video providers preserve subject and scene continuity across a batch.

After remote generation finishes, run a wrap-up check before leaving the GPU instance online:

```bash
.venv/bin/python -m auto_video remote wrapup \
  --host root@<autodl-host> \
  --remote-dir /root/auto-video/jobs/demo \
  --ssh-option Port=<ssh-port>
```

`remote wrapup` collects remote job directory size, disk free, ComfyUI queue state, and GPU utilization. When the queue and GPU are idle, it prints `release_recommended: true`; stop or release the rented instance in AutoDL to avoid continuing charges.

This adapter currently targets image-to-video jobs. Each shot should include an existing image reference; the adapter uploads that image to ComfyUI, patches the workflow prompt, seed, duration, resolution, frame rate, and output prefix, then downloads the first video output from ComfyUI history.

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
