# SSH Remote Worker Transport Design

Date: 2026-06-26
Workspace: `/root/auto_ai_vedio`
Phase: 4

## Purpose

Build the first real cloud-GPU handoff path for AI video generation jobs.

Phase 3 proved a portable worker bundle contract:

```text
local project -> export bundle -> worker run bundle -> import result
```

Phase 4 adds a thin SSH/rsync transport around that contract:

```text
local project
  -> export bundle
  -> rsync bundle to remote GPU machine
  -> ssh remote auto-video worker run
  -> rsync bundle back
  -> import result locally
```

The transport must not know how to build prompts, execute providers, or update manifests. It only moves a bundle, starts a remote command, and returns the result bundle.

## Chosen Approach

Use SSH plus rsync as the first remote transport.

Alternatives considered:

- Full cloud provider integration first: useful later, but too much vendor-specific behavior before the worker contract is exercised on a real machine.
- HTTP worker service first: cleaner for managed fleets, but requires server packaging, auth, routing, and lifecycle management before basic remote execution is proven.
- SSH/rsync first: simple, vendor-neutral, debuggable, and works with rented GPU boxes from many providers. This is the recommended Phase 4 path.

## In Scope

- Add an `auto-video remote run` CLI command.
- Export a worker bundle locally using existing Phase 3 helpers.
- Upload the bundle to a user-provided SSH target with `rsync`.
- Run `auto-video worker run <remote-bundle-dir>` on the remote host through `ssh`.
- Download the updated bundle back to a local result directory with `rsync`.
- Import the remote result bundle into the local project.
- Keep default tests offline by using a fake command runner and local temp directories.
- Make every command previewable through `--dry-run`.
- Preserve the existing `worker export|run|import`, `jobs`, and `generate` commands.

## Out Of Scope

- Creating, renting, or destroying cloud machines.
- Installing CUDA, drivers, Python, model weights, or provider dependencies on the remote host.
- Docker image building.
- Object storage upload/download.
- HTTP worker services.
- Async queues, polling dashboards, retries across machines, or multi-host scheduling.
- Real Seedance, Wan, or other paid API integration.
- Secret synchronization.

## User Workflow

Expected real-machine command:

```bash
auto-video remote run demo_project \
  --provider mock \
  --kind video \
  --host gpu-box \
  --remote-dir /data/auto-video/jobs/demo_ad_S01 \
  --local-dir /tmp/auto-video-remote/demo_ad_S01 \
  --remote-auto-video auto-video
```

The first implementation should also support:

```bash
auto-video remote run demo_project \
  --provider mock \
  --kind video \
  --host user@1.2.3.4 \
  --remote-dir /data/auto-video/jobs/demo_ad_S01 \
  --ssh-option StrictHostKeyChecking=no \
  --dry-run
```

`--dry-run` prints the planned local export path, upload command, remote run command, download command, and import action. It must not create a local manifest or run remote commands.

## CLI Contract

New command group:

```bash
auto-video remote run <project> \
  --host <ssh-target> \
  --remote-dir <remote-bundle-dir> \
  [--provider <provider>] \
  [--kind image|video|audio] \
  [--only S01,S03] \
  [--local-dir <local-work-dir>] \
  [--remote-auto-video <command>] \
  [--ssh-option <option>]... \
  [--rsync-option <option>]... \
  [--dry-run]
```

Defaults:

- `--kind video`
- `--provider` omitted uses project or shot defaults, matching `worker export`.
- `--local-dir` defaults to a generated directory under the system temp directory.
- `--remote-auto-video` defaults to `auto-video`.
- Local work directories are preserved in Phase 4 so users can inspect downloaded bundles and logs.
- Remote directories are preserved in Phase 4. The first implementation does not remove remote files automatically.

## Remote Directory Layout

If local work directory is:

```text
/tmp/auto-video-remote/demo_ad_20260626T101500/
```

the local bundle path is:

```text
/tmp/auto-video-remote/demo_ad_20260626T101500/bundle/
```

The remote bundle path is exactly the user-provided remote directory:

```text
/data/auto-video/jobs/demo_ad_S01/
```

The command uploads the contents of the local `bundle/` directory into the remote directory, runs the worker there, then downloads the remote directory back into local `bundle/`.

## Command Planning

Create a transport planner that returns structured commands before execution:

```python
RemoteRunPlan(
    project_root=Path(...),
    local_bundle=Path(...),
    host="gpu-box",
    remote_dir="/data/auto-video/jobs/demo_ad_S01",
    upload=["rsync", "-az", "--delete", ".../bundle/", "gpu-box:/data/auto-video/jobs/demo_ad_S01/"],
    run=["ssh", "gpu-box", "auto-video", "worker", "run", "/data/auto-video/jobs/demo_ad_S01"],
    download=["rsync", "-az", "--delete", "gpu-box:/data/auto-video/jobs/demo_ad_S01/", ".../bundle/"],
)
```

Rules:

- Commands are represented as `list[str]`, not shell strings.
- The implementation should execute commands with `subprocess.run(command, check=True, capture_output=True, text=True)`.
- `--ssh-option` values are expanded into repeated `-o <option>` pairs for `ssh`.
- `--rsync-option` values are appended to the default rsync command after `-az`.
- The remote `worker run` command is executed through `ssh`; it is not interpolated into a local shell command.

## File Responsibilities

Create:

- `src/auto_video/remote_transport.py`
  - Dataclasses for remote run options and plans.
  - Command planning for upload, remote worker run, and download.
  - A `CommandRunner` protocol and default subprocess runner.
  - `run_remote_worker()` orchestration.

Modify:

- `src/auto_video/cli.py`
  - Add `remote run`.
  - Parse SSH and rsync options.
  - Print JSON summaries for dry-run and real execution.

- `README.md`
  - Document the remote worker workflow.
  - Explain prerequisites for the remote host.

Tests:

- `tests/test_remote_transport.py`
  - Command planning.
  - Dry-run behavior.
  - Fake runner orchestration.
  - Error behavior.

- `tests/test_remote_cli.py`
  - CLI dry-run output.
  - CLI fake execution path without network.

## Data Flow

```text
auto-video remote run
  -> load_project(project)
  -> export_worker_bundle(project, local_bundle, ...)
  -> rsync local_bundle/ to host:remote_dir/
  -> ssh host remote_auto_video worker run remote_dir
  -> rsync host:remote_dir/ back to local_bundle/
  -> import_worker_results(project, local_bundle)
  -> print summary JSON
```

For `--dry-run`:

```text
auto-video remote run --dry-run
  -> plan paths and commands
  -> print summary JSON
  -> do not export, upload, ssh, download, or import
```

## Result Summary

Successful real execution returns JSON shaped like:

```json
{
  "dry_run": false,
  "project": "demo_ad",
  "host": "gpu-box",
  "remote_dir": "/data/auto-video/jobs/demo_ad_S01",
  "local_bundle": "/tmp/auto-video-remote/demo_ad_20260626T101500/bundle",
  "commands": {
    "upload": ["rsync", "-az", "--delete", "..."],
    "run": ["ssh", "gpu-box", "auto-video", "worker", "run", "/data/auto-video/jobs/demo_ad_S01"],
    "download": ["rsync", "-az", "--delete", "..."]
  },
  "imported": ["demo_ad:S01:video:mock"],
  "failed": []
}
```

Failed remote execution returns a user-facing error and does not import partial results unless the download step completes and `result.json` exists locally. The first implementation should fail fast on upload, ssh run, or download command errors.

## Error Handling

Use existing user-facing errors:

- `ConfigError` when required CLI options are missing or unsafe.
- `AssetError` when local or remote path planning would write outside allowed local paths.
- `ProviderError` or `ConfigError` wrapping failed `ssh` or `rsync` commands with a concise message and captured stderr.

Path and command safety:

- Local bundle directories must not be inside the project root.
- Remote paths must be absolute Unix-style paths beginning with `/`.
- Remote paths containing newline characters, null bytes, or shell control characters are rejected.
- Host values containing whitespace, newline characters, or shell control characters are rejected.
- Commands are executed without `shell=True`.
- The transport must not read or print secrets from environment variables.
- The transport must not delete remote directories in Phase 4.
- The transport must not delete local work directories in Phase 4.

## Remote Host Requirements

The remote host must already have:

- SSH access from the local machine.
- `rsync` installed.
- A working `auto-video` command or equivalent path passed with `--remote-auto-video`.
- Python dependencies needed by the selected provider.
- Any GPU drivers, model runtimes, or API credentials required by the selected provider.

Phase 4 does not install these dependencies. It should report command failures clearly so setup issues are easy to diagnose.

## Testing Strategy

Default tests remain offline and deterministic:

- No real SSH connection.
- No real rsync transfer.
- No network.
- No cloud account.
- No GPU.
- No API key.

Required tests:

- Planner builds upload, run, and download commands from host, remote dir, and local dir.
- Planner rejects unsafe host values and unsafe remote dirs.
- Dry-run prints planned commands and does not create `manifest.json`.
- Fake runner records upload, remote run, and download in order.
- Fake runner can simulate remote execution by calling local `run_worker_bundle()` on the copied bundle.
- Successful fake remote run imports results into the local project manifest.
- A failed upload does not run ssh, download, or import.
- A failed remote worker command does not import results unless a result bundle is available and explicitly downloaded by the normal flow.
- Existing worker and jobs tests continue passing.

## Success Criteria

Phase 4 is complete when this local fake-remote workflow passes in tests:

```bash
auto-video remote run demo_project \
  --provider mock \
  --kind video \
  --host fake-gpu \
  --remote-dir /tmp/remote-bundle \
  --local-dir /tmp/local-remote-run
```

and this real-machine dry run prints valid commands without touching the manifest:

```bash
auto-video remote run demo_project \
  --provider mock \
  --kind video \
  --host gpu-box \
  --remote-dir /data/auto-video/jobs/demo \
  --dry-run
```

All existing tests from Phase 3 must continue passing.

## Future Work

After Phase 4:

- Add a remote setup checker command such as `auto-video remote doctor`.
- Add provider-specific remote profiles for AutoDL, RunPod, Vast, or Aliyun ECS.
- Add object storage transport.
- Add async remote job polling.
- Add real GPU providers behind the existing provider gateway.
- Add Docker image packaging once the SSH flow proves the execution boundary.
- Add explicit local and remote cleanup commands once remote run logs are stable.
