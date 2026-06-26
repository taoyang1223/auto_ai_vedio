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

## Prototype Migration

The old `/root/ai_vedio` project maps into this MVP as follows:

- `batch_plans/*.json` becomes `shots.json`.
- `edl/*.json` becomes render settings plus manifest-derived EDL.
- `tools/providers/*.py` becomes provider adapters.
- `tools/assemble2.py` becomes `src/auto_video/render.py`.
- production SOP documents become validation, probe, and README guidance.

Default tests use the mock provider and do not require API keys, network, cloud GPU, or large video files.
