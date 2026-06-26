# External Command Provider Implementation Plan

> **For agentic workers:** Implement test-first. Default tests must remain offline and deterministic.

**Goal:** Add a configurable `external_command` provider mode so Wan, ComfyUI, Seedance API wrappers, and other real model scripts can plug into the provider job runtime.

**Architecture:** Add `ExternalCommandProvider` under `src/auto_video/providers/`. It writes a Seedance-style job payload to `.auto-video/provider-jobs/`, invokes a configured command with `--job`, `--project-root`, and `--output`, then maps the result into `ProviderResult`. The provider registry receives project provider config so project-defined provider names can resolve without hardcoding each model.

---

## Task 1: Provider Model And Registry

- [x] Write tests for project-defined provider names and external command config.
- [x] Relax provider validation so configured provider names are accepted.
- [x] Pass project provider config into `get_provider()`.
- [x] Raise user-facing config errors for unavailable providers.

## Task 2: External Command Provider

- [x] Write tests for successful fake adapter execution.
- [x] Write tests for failed adapter execution.
- [x] Write tests for timeout and unsafe command config.
- [x] Write tests that job payload includes controls and resolved references.
- [x] Implement `ExternalCommandProvider`.

## Task 3: Worker Compatibility And Documentation

- [x] Prove `worker export/run/import` works with an external command provider.
- [x] Document `external_command` provider config in `README.md`.
- [x] Run focused tests.
- [x] Run full test suite.
- [x] Run CLI smoke with a fake adapter.

## Verification Commands

```bash
.venv/bin/python -m pytest tests/test_external_command_provider.py tests/test_provider_jobs.py tests/test_worker_cli.py -v
.venv/bin/python -m pytest -v
```

## Success Criteria

- A project can set `default_video_provider: local_wan` and define `providers.local_wan.mode: external_command`.
- `jobs submit --provider local_wan --kind video` invokes the configured adapter and records success.
- Failures are recorded as failed provider results instead of crashing the manifest write path.
- Existing mock, worker, remote, and doctor flows still pass.
