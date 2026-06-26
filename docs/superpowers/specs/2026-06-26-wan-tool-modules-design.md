# Wan Tool Modules Design

Date: 2026-06-26
Workspace: `/root/auto_ai_vedio`
Phase: 10

## Purpose

Make the Wan adapter and runtime doctor usable on a remote GPU host after installing the `auto-video` package.

Phases 7 through 9 added scripts under `scripts/`:

- `scripts/wan_http_adapter.py`
- `scripts/wan_runtime_doctor.py`
- `scripts/wan_remote_smoke.py`

Those work from a repository checkout, but remote workers often run from an installed package or a worker bundle directory. Depending on `scripts/...` being present in the remote login directory is brittle.

Phase 10 moves reusable logic into package modules and keeps the scripts as compatibility wrappers.

## New Stable Entrypoints

```bash
python -m auto_video.wan_http_adapter
python -m auto_video.wan_runtime_doctor
python -m auto_video.wan_remote_smoke
```

The wrapper scripts remain:

```bash
python scripts/wan_http_adapter.py
python scripts/wan_runtime_doctor.py
python scripts/wan_remote_smoke.py
```

## Configuration Change

Recommended provider config becomes:

```yaml
providers:
  wan_http:
    mode: external_command
    timeout_seconds: 1800
    command:
      - python
      - -m
      - auto_video.wan_http_adapter
      - --base-url-env
      - WAN_BASE_URL
```

Wan remote smoke should default to:

```text
python -m auto_video.wan_runtime_doctor
```

instead of `python scripts/wan_runtime_doctor.py`.

## File Responsibilities

Create:

- `src/auto_video/wan_http_adapter.py`
- `src/auto_video/wan_runtime_doctor.py`

Modify:

- `scripts/wan_http_adapter.py`
- `scripts/wan_runtime_doctor.py`
- `scripts/wan_remote_smoke.py`
- `src/auto_video/wan_remote_smoke.py`
- `README.md`

## Compatibility

The script wrappers should import from `src/` when running from a source checkout, then call the package module `main()`.

Existing tests that call scripts should keep passing. New tests should prove `python -m auto_video.wan_http_adapter` and `python -m auto_video.wan_runtime_doctor` work with fake servers.

## Out Of Scope

- Wan model installation.
- Wan server implementation.
- Docker packaging.
- PyPI packaging changes beyond adding importable modules.
