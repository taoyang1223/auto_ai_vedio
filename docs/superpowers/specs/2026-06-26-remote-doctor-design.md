# Remote Doctor Design

Date: 2026-06-26
Workspace: `/root/auto_ai_vedio`
Phase: 5

## Purpose

Add a remote environment preflight command for rented GPU machines.

Phase 4 added `auto-video remote run`, which can export a worker bundle, upload it with `rsync`, run `auto-video worker run` over `ssh`, download results, and import them locally. The next practical risk is remote setup failure: SSH may be misconfigured, `rsync` may be missing, `auto-video` may not be installed, or the remote work directory may not be writable.

Phase 5 adds:

```bash
auto-video remote doctor \
  --host gpu-box \
  --remote-dir /data/auto-video/jobs/demo \
  --remote-auto-video auto-video
```

The command returns a structured JSON report that tells the user which prerequisite is ready and which one needs attention before running a real remote job.

## Design Goal

Support this workflow:

```bash
auto-video remote doctor --host gpu-box --remote-dir /data/auto-video/jobs/demo
auto-video remote run demo_project --provider mock --kind video --host gpu-box --remote-dir /data/auto-video/jobs/demo
```

The doctor command should be safe to run before every remote job. It does not create a project manifest, export a bundle, upload assets, run providers, install dependencies, or modify local project files.

## Chosen Approach

Create a small `remote_doctor` module that reuses the Phase 4 command runner pattern and remote option validation.

Alternatives considered:

- Put all doctor logic inside `remote_transport.py`: fewer files, but it would mix execution workflow with diagnostics and make that file too broad.
- Build provider-specific cloud checks first: useful later, but premature before generic SSH/rsync health is reliable.
- Create a dedicated `remote_doctor.py`: clear boundary, testable with fake runners, and easy to extend with provider-specific checks later. This is the recommended path.

## In Scope

- Add `auto-video remote doctor`.
- Validate host and remote directory using the same safety expectations as `remote run`.
- Run local/remote prerequisite checks through a command runner:
  - local `ssh` command availability
  - local `rsync` command availability
  - SSH connectivity
  - remote `rsync` availability
  - remote `auto-video` command availability
  - remote worker CLI availability
  - remote directory creation/writability
- Return JSON with per-check status, command, stdout/stderr snippets, and fix guidance.
- Support `--dry-run` to print planned checks without running SSH, rsync, or remote commands.
- Exit 0 when all checks pass.
- Exit 1 when one or more checks fail.
- Keep default tests offline by using fake command runners.

## Out Of Scope

- Creating, renting, starting, stopping, or destroying cloud machines.
- Installing local or remote dependencies.
- Installing CUDA, drivers, model weights, Python packages, or provider runtimes.
- Uploading bundles or assets.
- Running generation providers.
- Running `auto-video remote run`.
- Checking actual GPU availability.
- Checking paid provider credentials.
- Provider-specific platform profiles for AutoDL, RunPod, Vast, or Aliyun.

## CLI Contract

New command:

```bash
auto-video remote doctor \
  --host <ssh-target> \
  --remote-dir <remote-bundle-dir> \
  [--remote-auto-video <command>] \
  [--ssh-option <option>]... \
  [--dry-run]
```

Defaults:

- `--remote-auto-video auto-video`
- `--ssh-option` may be provided multiple times and is expanded into repeated `-o <option>` pairs.
- `--dry-run` validates inputs and prints planned checks without executing them.

The command does not require a local project path. It only validates the remote execution environment.

## Report Format

Successful report:

```json
{
  "ok": true,
  "host": "gpu-box",
  "remote_dir": "/data/auto-video/jobs/demo",
  "checks": [
    {
      "name": "local_ssh",
      "status": "ok",
      "command": ["ssh", "-V"],
      "message": "local ssh command is available",
      "fix": null
    },
    {
      "name": "ssh_connectivity",
      "status": "ok",
      "command": ["ssh", "gpu-box", "true"],
      "message": "ssh connection succeeded",
      "fix": null
    }
  ]
}
```

Failed report:

```json
{
  "ok": false,
  "host": "gpu-box",
  "remote_dir": "/data/auto-video/jobs/demo",
  "checks": [
    {
      "name": "remote_rsync",
      "status": "failed",
      "command": ["ssh", "gpu-box", "command", "-v", "rsync"],
      "message": "remote rsync command was not found",
      "fix": "Install rsync on the remote host."
    }
  ]
}
```

The report should include every check, not stop at the first failure, except when host or path validation fails before checks can be planned.

Dry-run report:

```json
{
  "ok": true,
  "host": "gpu-box",
  "remote_dir": "/data/auto-video/jobs/demo",
  "dry_run": true,
  "checks": [
    {
      "name": "local_ssh",
      "status": "planned",
      "command": ["ssh", "-V"],
      "message": "planned local ssh availability check",
      "fix": null
    }
  ]
}
```

## Check List

Phase 5 should include these checks:

1. `local_ssh`
   - Command: `["ssh", "-V"]`
   - Success means the local `ssh` executable is available.
   - Failure fix: install OpenSSH client locally or update PATH.

2. `local_rsync`
   - Command: `["rsync", "--version"]`
   - Success means the local `rsync` executable is available.
   - Failure fix: install rsync locally or update PATH.

3. `ssh_connectivity`
   - Command: `["ssh", *ssh_option_args, host, "true"]`
   - Success means SSH can connect to the host.
   - Failure fix: verify host, key, username, port, and `--ssh-option` values.

4. `remote_rsync`
   - Command: `["ssh", *ssh_option_args, host, "command", "-v", "rsync"]`
   - Success means remote `rsync` exists.
   - Failure fix: install rsync on the remote host.

5. `remote_auto_video`
   - Command: `["ssh", *ssh_option_args, host, remote_auto_video, "--help"]`
   - Success means the configured remote command is callable.
   - Failure fix: install the project on the remote host or pass `--remote-auto-video`.

6. `remote_worker_cli`
   - Command: `["ssh", *ssh_option_args, host, remote_auto_video, "worker", "run", "--help"]`
   - Success means the remote command exposes the worker CLI.
   - Failure fix: update the remote project version.

7. `remote_dir_writable`
   - Command: `["ssh", *ssh_option_args, host, "mkdir", "-p", remote_dir]`
   - Then: `["ssh", *ssh_option_args, host, "test", "-w", remote_dir]`
   - Success means the remote directory exists and is writable.
   - Failure fix: create the directory with proper permissions or choose another `--remote-dir`.

## Command Safety

Use the same safety rules as Phase 4:

- Host cannot be empty and cannot contain whitespace or shell control characters.
- Remote directory must be an absolute Unix path beginning with `/`.
- Remote directory cannot be `/`.
- Remote directory cannot contain `..` path segments.
- Remote command tokens cannot contain whitespace or shell control characters.
- SSH options cannot contain shell control characters.
- Commands are executed with `subprocess.run([...], shell=False)`.
- Reports must not print environment variables or secret values.

`remote_dir_writable` may create the requested remote directory with `mkdir -p`. This is the only remote filesystem write in Phase 5.

## File Responsibilities

Create:

- `src/auto_video/remote_doctor.py`
  - Doctor option dataclass.
  - Doctor check dataclass.
  - Command planning for checks.
  - `run_remote_doctor()` orchestration.

Modify:

- `src/auto_video/remote_transport.py`
  - Expose shared validation and SSH option helpers if needed.
  - Keep remote execution behavior unchanged.

- `src/auto_video/cli.py`
  - Add `remote doctor`.
  - Print JSON report.
  - Return exit code 0 for all-ok reports and 1 for failed reports.

- `README.md`
  - Document remote doctor before remote run.

Tests:

- `tests/test_remote_doctor.py`
  - Check planning.
  - Successful fake report.
  - Failure report with all checks included.
  - Safety validation.

- `tests/test_remote_cli.py`
  - CLI success path with fake runner.
  - CLI failure path returns exit code 1.

## Data Flow

```text
auto-video remote doctor
  -> parse host, remote-dir, remote-auto-video, ssh options
  -> validate command inputs
  -> build check commands
  -> if dry-run, print planned check records and return 0
  -> run each check through CommandRunner
  -> convert results into check records
  -> print JSON report
  -> return 0 if report.ok else 1
```

The command is independent of local projects and manifests.

## Error Handling

Validation errors remain user-facing `ConfigError` exceptions and are handled by the existing CLI error wrapper.

Command failures do not raise immediately inside doctor orchestration. They become failed check records so the user can see every missing prerequisite in one report. The only exceptions are validation errors that make check construction unsafe.

Each failed check should include:

- check name
- status `failed`
- command
- concise message
- captured stderr or stdout snippet when useful
- fix guidance

## Testing Strategy

Default tests remain offline and deterministic:

- No real SSH.
- No real rsync.
- No network.
- No cloud account.
- No GPU.

Required tests:

- Check planner builds every expected command.
- Dry-run report includes every planned check and does not call the command runner.
- Unsafe host and unsafe remote directory are rejected.
- Successful fake runner returns `ok: true`.
- Failed fake runner returns `ok: false`.
- Failure report includes all planned checks.
- CLI returns 0 for successful fake doctor report.
- CLI returns 1 for failed fake doctor report.
- Existing `remote run`, `worker`, and `jobs` tests continue passing.

## Success Criteria

Phase 5 is complete when:

```bash
auto-video remote doctor \
  --host gpu-box \
  --remote-dir /data/auto-video/jobs/demo \
  --dry-run
```

or the implementation equivalent can print the planned check commands without network access, and fake-runner tests can prove both all-ok and failure reports.

For the real command:

```bash
auto-video remote doctor --host gpu-box --remote-dir /data/auto-video/jobs/demo
```

it should return JSON, exit 0 when all checks pass, and exit 1 when one or more checks fail.

All existing tests from Phase 4 must continue passing.

## Future Work

After Phase 5:

- Add optional GPU checks such as `nvidia-smi`.
- Add provider-specific checks for ComfyUI, Wan, Seedance API, or model paths.
- Add platform profiles for AutoDL, RunPod, Vast, and Aliyun.
- Add `remote doctor --json-output <path>` for saved reports.
- Add a setup guide generated from failed checks.
