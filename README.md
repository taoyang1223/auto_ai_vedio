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

## Cloud Worker Contract

Phase 3 adds a portable worker bundle workflow:

    .venv/bin/python -m auto_video worker export demo_project --provider mock --kind video --out /tmp/av-bundle --force
    .venv/bin/python -m auto_video worker run /tmp/av-bundle
    .venv/bin/python -m auto_video worker import demo_project /tmp/av-bundle

The first worker is local and deterministic. It proves the export/run/import contract without needing a GPU, cloud account, object storage, FFmpeg, or API key. A future cloud transport only needs to move the bundle to a rented GPU machine, run the same worker command, and bring the result bundle back.

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
