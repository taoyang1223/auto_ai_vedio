# Wan HTTP Adapter Implementation Plan

> **For agentic workers:** Implement test-first. Tests must use a local fake HTTP server and must not require Wan, GPU, internet, API keys, or model weights.

**Goal:** Add `scripts/wan_http_adapter.py`, a concrete adapter for Phase 6 `external_command` providers.

**Architecture:** The script reads a Phase 6 job payload, derives Wan request settings from Seedance-style controls, posts to `/i2v` when an image reference exists or `/t2v` otherwise, and writes the returned video bytes to `--output`.

---

## Task 1: Adapter Tests

- [x] Write fake HTTP server tests for I2V request mapping.
- [x] Write fake HTTP server tests for T2V fallback.
- [x] Write token/base-url-env test.
- [x] Write JSON error response test.
- [x] Write external provider integration test using the real adapter script.

## Task 2: Adapter Implementation

- [x] Implement argument parsing.
- [x] Resolve base URL from `--base-url` or `--base-url-env`.
- [x] Read optional bearer token from `--token-env`.
- [x] Build Wan JSON from the Phase 6 payload.
- [x] Base64 encode the first existing image reference for `/i2v`.
- [x] Use `/t2v` when no image reference exists.
- [x] Treat JSON responses as errors and binary responses as video output.

## Task 3: Docs And Verification

- [x] Document `wan_http` provider config in README.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Run CLI smoke with local fake adapter/server path when practical.

## Verification Commands

```bash
.venv/bin/python -m pytest tests/test_wan_http_adapter.py -v
.venv/bin/python -m pytest -v
```

## Success Criteria

- `scripts/wan_http_adapter.py` can be used as an `external_command` provider.
- I2V and T2V requests are deterministic in tests.
- Adapter errors are visible through non-zero exit codes, so Phase 6 records provider failures.
- Existing tests still pass.
