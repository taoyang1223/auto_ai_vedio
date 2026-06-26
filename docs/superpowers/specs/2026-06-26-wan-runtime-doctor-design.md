# Wan Runtime Doctor Design

Date: 2026-06-26
Workspace: `/root/auto_ai_vedio`
Phase: 8

## Purpose

Add a preflight tool for the Wan HTTP runtime itself.

Phase 7 added `scripts/wan_http_adapter.py`, which can call a running Wan service. The missing practical step is confirming that the Wan HTTP service is reachable and model endpoints are loaded before spending time on `jobs submit` or `remote run`.

Phase 8 adds:

```bash
python scripts/wan_runtime_doctor.py --base-url-env WAN_BASE_URL --require-i2v
```

The tool calls `GET /health`, prints a JSON report, exits 0 when required checks pass, and exits 1 when the service is unhealthy or required capabilities are missing.

## Runtime Contract

The Wan HTTP service is expected to expose:

```text
GET /health
```

Example response:

```json
{
  "status": "ok",
  "i2v_loaded": true,
  "t2v_loaded": true,
  "gpu_free_gb": 28.5,
  "offload": false,
  "tf32": true
}
```

## CLI Contract

```bash
python scripts/wan_runtime_doctor.py \
  [--base-url <url> | --base-url-env <env-name>] \
  [--token-env <env-name>] \
  [--timeout <seconds>] \
  [--require-i2v] \
  [--require-t2v]
```

Defaults:

- output is always JSON
- timeout defaults to 30 seconds
- no generation request is sent
- no files are written

## Report Format

```json
{
  "ok": true,
  "base_url": "http://127.0.0.1:8082",
  "checks": [
    {
      "name": "health",
      "status": "ok",
      "message": "Wan health endpoint responded",
      "details": {
        "status": "ok",
        "i2v_loaded": true,
        "t2v_loaded": true,
        "gpu_free_gb": 28.5
      }
    }
  ]
}
```

Failed checks use status `failed` and include a concise `fix`.

## Safety

- Token values are read from environment variables and never printed.
- The tool only sends `GET /health`.
- No bundle, project, manifest, provider job, or remote directory is modified.
- It uses Python standard library networking, so no new runtime dependency is introduced.

## Tests

Use a local fake HTTP server:

- healthy `/health` exits 0 and records service fields
- bearer token header is sent when `--token-env` is provided
- `--require-i2v` fails when `i2v_loaded` is false
- `--require-t2v` fails when `t2v_loaded` is false
- missing base URL env exits 1 with a useful message

## Out Of Scope

- Starting the Wan service.
- Installing model weights.
- Checking CUDA directly.
- Opening SSH tunnels.
- Sending `/i2v` or `/t2v` generation requests.

Those remain deployment and runtime tasks after the health gate passes.
