# auto_ai_vedio

Seedance-inspired AI video production CLI pipeline.

## MVP Workflow

```bash
python3 -m auto_video init demo_project
python3 -m auto_video validate demo_project
python3 -m auto_video images demo_project --dry-run
python3 -m auto_video generate demo_project --dry-run
python3 -m auto_video generate demo_project --provider mock
python3 -m auto_video assemble demo_project --dry-run
python3 -m auto_video probe demo_project --dry-run
```

## Design

See `docs/superpowers/specs/2026-06-26-ai-video-cli-pipeline-design.md`.

## Prototype Migration

The old `/root/ai_vedio` project maps into this MVP as follows:

- `batch_plans/*.json` becomes `shots.json`.
- `edl/*.json` becomes render settings plus manifest-derived EDL.
- `tools/providers/*.py` becomes provider adapters.
- `tools/assemble2.py` becomes `src/auto_video/render.py`.
- production SOP documents become validation, probe, and README guidance.

Default tests use the mock provider and do not require API keys, network, cloud GPU, or large video files.
