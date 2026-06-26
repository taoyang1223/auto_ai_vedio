# Wan GPU Runbook Design

## Problem

The project can already export worker bundles, run them over SSH, call a Wan HTTP service, and smoke-test the remote workflow. The missing practical layer is a single, reviewable runbook for a rented GPU host.

The old project notes found the most reliable pattern:

- run the generation job on the GPU host
- let the remote worker call `http://127.0.0.1:8082`
- avoid fragile long-lived local SSH tunnels
- always preflight `/health` before spending GPU time

## Goal

Add a deterministic planner that prints the end-to-end rented GPU workflow without creating cloud machines or executing SSH commands by default.

The planner should answer:

1. how to install or update `auto-video` on the remote host
2. how to start or manually start the Wan HTTP service
3. how to run remote doctor and Wan runtime doctor
4. how to run the actual remote worker with `WAN_BASE_URL`
5. what assumptions remain manual, especially GPU rental and shutdown

## Entrypoints

```bash
python -m auto_video.wan_gpu_runbook
python scripts/wan_gpu_runbook.py
```

Both should support JSON output by default and Markdown output for copyable human instructions.

## Command Model

The runbook is a plan only. It does not execute commands. It may include shell snippets inside remote `bash -lc` commands for install/start steps, but all commands must be returned as argv arrays so callers can inspect or copy them.

The remote worker should default to venv entrypoints:

```text
/opt/auto-ai-video/.venv/bin/python
/opt/auto-ai-video/.venv/bin/auto-video
```

Wan should default to:

```text
WAN_BASE_URL=http://127.0.0.1:8082
```

## Non-Goals

- Creating, renting, stopping, or billing cloud GPU machines.
- Installing CUDA, model weights, or Wan itself.
- Guessing a model-specific Wan server command when the user has not supplied one.
- Running SSH commands automatically.

## Files

- `src/auto_video/wan_gpu_runbook.py`
- `scripts/wan_gpu_runbook.py`
- `tests/test_wan_gpu_runbook.py`
- `README.md`
