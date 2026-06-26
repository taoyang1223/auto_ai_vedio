# Wan Remote Smoke Implementation Plan

> **For agentic workers:** Implement test-first. Default tests must not require SSH, rsync, Wan, GPU, internet, or cloud accounts.

**Goal:** Let users pass `WAN_BASE_URL` into remote workers and provide a `wan_remote_smoke.py` planner/executor for the real cloud GPU smoke sequence.

---

## Task 1: Remote Worker Environment

- [x] Add planner tests for `RemoteRunOptions.remote_env`.
- [x] Validate env names and values.
- [x] Add `--remote-env NAME=value` to `auto-video remote run`.
- [x] Keep upload/download unchanged.

## Task 2: Wan Remote Smoke Planner

- [x] Add `src/auto_video/wan_remote_smoke.py` for testable planning/execution.
- [x] Add `scripts/wan_remote_smoke.py` wrapper.
- [x] Plan `remote doctor`, remote `wan_runtime_doctor.py`, and `remote run`.
- [x] Support `--execute` with a command runner and fail-fast behavior.

## Task 3: Docs And Verification

- [x] Document the smoke sequence in README.
- [x] Run focused tests.
- [x] Run full suite.
- [x] Run a dry-run CLI smoke.

## Verification Commands

```bash
.venv/bin/python -m pytest tests/test_remote_transport.py tests/test_remote_cli.py tests/test_wan_remote_smoke.py -v
.venv/bin/python -m pytest -v
```

## Success Criteria

- `remote run --remote-env WAN_BASE_URL=... --dry-run` shows the env assignment in the remote worker command.
- `wan_remote_smoke.py` prints a JSON plan by default.
- `wan_remote_smoke.py --execute` runs planned commands in order with fake-runner test coverage.
- Existing remote, worker, Wan adapter, and Wan runtime doctor tests keep passing.
