# Wan Tool Modules Implementation Plan

> **For agentic workers:** Preserve script compatibility while adding package module entrypoints. Tests must remain offline.

**Goal:** Support stable remote commands such as `python -m auto_video.wan_http_adapter` and `python -m auto_video.wan_runtime_doctor`.

---

## Task 1: Module Entrypoint Tests

- [x] Add tests for `python -m auto_video.wan_http_adapter` with fake Wan server.
- [x] Add tests for `python -m auto_video.wan_runtime_doctor` with fake health server.
- [x] Ensure existing script tests keep passing.

## Task 2: Refactor Scripts Into Modules

- [x] Move Wan HTTP adapter logic into `src/auto_video/wan_http_adapter.py`.
- [x] Move Wan runtime doctor logic into `src/auto_video/wan_runtime_doctor.py`.
- [x] Turn `scripts/wan_http_adapter.py` into a wrapper.
- [x] Turn `scripts/wan_runtime_doctor.py` into a wrapper.
- [x] Keep `scripts/wan_remote_smoke.py` as a wrapper around package code.

## Task 3: Remote Smoke Defaults And Docs

- [x] Change `WanRemoteSmokeOptions.remote_wan_doctor` default to `auto_video.wan_runtime_doctor`.
- [x] Plan remote runtime doctor as `python -m auto_video.wan_runtime_doctor`.
- [x] Update README provider config to use `python -m auto_video.wan_http_adapter`.
- [x] Run focused and full tests.

## Verification Commands

```bash
.venv/bin/python -m pytest tests/test_wan_http_adapter.py tests/test_wan_runtime_doctor.py tests/test_wan_remote_smoke.py -v
.venv/bin/python -m pytest -v
```

## Success Criteria

- Module entrypoints work.
- Legacy script paths still work.
- Wan remote smoke no longer assumes `scripts/wan_runtime_doctor.py` is present on the remote host.
- Full suite passes.
