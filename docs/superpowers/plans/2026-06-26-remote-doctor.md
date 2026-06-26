# Remote Doctor Implementation Plan

> **For agentic workers:** Implement task-by-task with tests first. Keep default verification offline: no real SSH, rsync, network, cloud account, or GPU.

**Goal:** Add `auto-video remote doctor` so users can preflight rented GPU hosts before running `auto-video remote run`.

**Architecture:** Create `src/auto_video/remote_doctor.py` for check planning, safe command orchestration, dry-run reports, and fake-runner testability. Reuse Phase 4 validation and command runner types from `remote_transport.py`. Keep CLI integration thin: parse flags, call `run_remote_doctor()`, print JSON, return 0 for all-ok/planned reports and 1 when checks fail.

**Tech Stack:** Python 3.12, dataclasses, argparse, subprocess command runner protocol, pytest, existing CLI JSON patterns.

---

## File Map

- Create `src/auto_video/remote_doctor.py`: doctor options, check plans, check records, report orchestration.
- Modify `src/auto_video/cli.py`: add `remote doctor`.
- Modify `README.md`: document remote doctor before remote run.
- Add `tests/test_remote_doctor.py`: planner, dry-run, success/failure, safety.
- Extend `tests/test_remote_cli.py`: CLI success, failure exit code, dry-run.

## Task 1: Doctor Planner And Reports

- [x] Write failing tests for planned commands:
  - local `ssh -V`
  - local `rsync --version`
  - SSH connectivity
  - remote `rsync`
  - remote `auto-video --help`
  - remote `auto-video worker run --help`
  - remote `mkdir -p <dir>` and `test -w <dir>`
- [x] Write dry-run test proving no runner calls occur.
- [x] Implement `RemoteDoctorOptions`, `DoctorCheckPlan`, `DoctorCheckRecord`, `build_remote_doctor_plan()`, `run_remote_doctor()`, and JSON report assembly.
- [x] Convert command failures into failed check records instead of raising early.

## Task 2: CLI Integration

- [x] Add `auto-video remote doctor` parser with `--host`, `--remote-dir`, `--remote-auto-video`, repeated `--ssh-option`, and `--dry-run`.
- [x] Print JSON report for every doctor run.
- [x] Return 0 for all-ok and dry-run reports.
- [x] Return 1 when any check fails.

## Task 3: Documentation And Verification

- [x] Document remote doctor in `README.md`.
- [x] Run focused tests:

```bash
.venv/bin/python -m pytest tests/test_remote_doctor.py tests/test_remote_cli.py -v
```

- [x] Run full verification:

```bash
.venv/bin/python -m pytest -v
```

- [x] Run CLI smoke:

```bash
.venv/bin/python -m auto_video remote doctor --host gpu-box --remote-dir /data/auto-video/jobs/demo --dry-run
```

## Success Criteria

- `auto-video remote doctor --dry-run` prints all planned checks without network access.
- Fake-runner tests prove all-ok and failed JSON reports.
- CLI exits 1 for failed checks and 0 for all-ok/dry-run.
- Existing `remote run`, `worker`, and `jobs` tests still pass.
