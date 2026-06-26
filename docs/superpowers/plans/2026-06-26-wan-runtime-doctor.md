# Wan Runtime Doctor Implementation Plan

> **For agentic workers:** Implement test-first. Use a fake local HTTP server; do not require Wan, GPU, internet, or credentials.

**Goal:** Add `scripts/wan_runtime_doctor.py` to preflight a running Wan HTTP service before using `wan_http_adapter.py`.

**Architecture:** A standalone standard-library script resolves base URL/token from CLI/env, calls `GET /health`, builds a JSON report, and exits 0 only when required checks pass.

---

## Task 1: Tests

- [x] Test healthy `/health` response exits 0.
- [x] Test bearer token header is sent through `--token-env`.
- [x] Test `--require-i2v` fails when `i2v_loaded` is false.
- [x] Test `--require-t2v` fails when `t2v_loaded` is false.
- [x] Test missing base URL env exits 1 with a useful JSON report.

## Task 2: Implementation

- [x] Implement CLI parser.
- [x] Resolve base URL from `--base-url` or `--base-url-env`.
- [x] Read optional token from `--token-env` without printing it.
- [x] Call `GET /health`.
- [x] Build JSON checks and exit code.
- [x] Keep dependencies to Python standard library.

## Task 3: Docs And Verification

- [x] Document doctor usage in README.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Run local fake-server CLI smoke.

## Verification Commands

```bash
.venv/bin/python -m pytest tests/test_wan_runtime_doctor.py -v
.venv/bin/python -m pytest -v
```

## Success Criteria

- `scripts/wan_runtime_doctor.py` can verify a local tunneled Wan service.
- It can require I2V and/or T2V model readiness.
- Failures are clear and machine-readable JSON.
- Existing adapter and provider tests keep passing.
