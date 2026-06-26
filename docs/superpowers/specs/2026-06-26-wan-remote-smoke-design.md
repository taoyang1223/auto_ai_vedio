# Wan Remote Smoke Design

Date: 2026-06-26
Workspace: `/root/auto_ai_vedio`
Phase: 9

## Purpose

Connect the existing remote worker and Wan runtime pieces into a practical cloud GPU smoke flow.

Phase 7 added `wan_http_adapter.py`.
Phase 8 added `wan_runtime_doctor.py`.
Phase 4 remote execution can run worker bundles over SSH, but it cannot explicitly pass runtime environment variables such as `WAN_BASE_URL` to the remote worker process.

Phase 9 adds:

- `auto-video remote run --remote-env NAME=value`
- `scripts/wan_remote_smoke.py` to plan or execute:
  1. `auto-video remote doctor`
  2. remote `wan_runtime_doctor.py`
  3. `auto-video remote run --provider wan_http`

## Workflow

```bash
python scripts/wan_remote_smoke.py \
  --project demo_project \
  --host gpu-box \
  --remote-dir /data/auto-video/jobs/demo \
  --wan-base-url http://127.0.0.1:8082 \
  --require-i2v
```

Default behavior prints a JSON plan and does not contact the remote host.

To execute:

```bash
python scripts/wan_remote_smoke.py ... --execute
```

## Remote Environment

`remote run` accepts repeatable environment assignments:

```bash
auto-video remote run demo_project \
  --provider wan_http \
  --host gpu-box \
  --remote-dir /data/auto-video/jobs/demo \
  --remote-env WAN_BASE_URL=http://127.0.0.1:8082
```

The remote run command becomes:

```text
ssh gpu-box WAN_BASE_URL=http://127.0.0.1:8082 auto-video worker run /data/auto-video/jobs/demo
```

Only the remote worker command receives these assignments. Upload and download commands do not change.

## Safety

- Environment variable names must match `[A-Za-z_][A-Za-z0-9_]*`.
- Environment values cannot contain whitespace or shell control characters.
- `--remote-env` is intended for non-secret runtime settings such as `WAN_BASE_URL`.
- Secret tokens should be configured on the remote host and referenced by `--token-env`.
- Commands continue to use argument lists, not local shell interpolation.

## Wan Smoke Plan

The smoke planner outputs:

```json
{
  "dry_run": true,
  "commands": {
    "remote_doctor": ["python", "-m", "auto_video", "remote", "doctor", "..."],
    "wan_runtime_doctor": ["ssh", "gpu-box", "WAN_BASE_URL=http://127.0.0.1:8082", "python", "scripts/wan_runtime_doctor.py", "..."],
    "remote_run": ["python", "-m", "auto_video", "remote", "run", "..."]
  }
}
```

When `--execute` is passed, commands run in that order and the script exits on the first failure.

## Out Of Scope

- Installing Wan on the remote host.
- Starting or supervising the Wan HTTP service.
- Passing secret tokens over SSH command lines.
- Creating cloud machines.

Those remain platform setup tasks.

## Tests

- Remote run planner includes environment assignment before `auto-video worker run`.
- CLI dry-run exposes the environment assignment.
- Unsafe `--remote-env` values are rejected.
- Wan smoke planner prints all three commands.
- Wan smoke execution can be tested with a fake command runner.
