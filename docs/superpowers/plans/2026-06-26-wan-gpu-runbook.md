# Wan GPU Runbook Implementation Plan

> **For agentic workers:** Keep this offline and deterministic. Do not require SSH, GPU, internet, cloud accounts, or Wan during tests.

**Goal:** Add a stable runbook generator for rented GPU Wan workflows.

---

## Task 1: Tests

- [x] Test JSON runbook includes install, Wan start/manual, preflight, remote run, and shutdown phases.
- [x] Test remote smoke commands use `/opt/auto-ai-video/.venv/bin/python` and `/opt/auto-ai-video/.venv/bin/auto-video`.
- [x] Test explicit `--wan-start-command` is represented as a remote command.
- [x] Test Markdown formatting contains copyable shell blocks.
- [x] Test script/module entrypoints print valid output.

## Task 2: Planner

- [x] Add `WanGpuRunbookOptions`.
- [x] Add `build_wan_gpu_runbook()`.
- [x] Reuse `build_wan_remote_smoke_plan()` for doctor and run commands.
- [x] Validate host, remote dirs, SSH options, and non-shell tokens.
- [x] Keep start command optional and manual by default.

## Task 3: Entrypoints And Docs

- [x] Add `python -m auto_video.wan_gpu_runbook`.
- [x] Add `scripts/wan_gpu_runbook.py` wrapper.
- [x] Document the rented GPU workflow in README.

## Verification Commands

```bash
.venv/bin/python -m pytest tests/test_wan_gpu_runbook.py -v
.venv/bin/python -m pytest -v
```

## Success Criteria

- The generated runbook is useful for a real rented GPU session.
- Default tests stay offline.
- Existing remote, worker, and Wan tests keep passing.
