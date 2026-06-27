from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .errors import AutoVideoError
from .continuity import extract_tail_frames
from .job_store import JobStore
from .pipeline import generate_audio, generate_images, generate_videos, plan_jobs, submit_jobs
from .probe import probe_project
from .project import load_project
from .render import assemble_project
from .remote_doctor import RemoteDoctorOptions, run_remote_doctor
from .remote_profiles import build_remote_run_options_from_profile, list_remote_profiles
from .remote_transport import run_remote_worker
from .remote_wrapup import RemoteWrapupOptions, run_remote_wrapup
from .templates import init_project, list_templates
from .validation import validate_project
from .web import run_web_server
from .worker_bundle import export_worker_bundle, import_worker_results
from .worker_runner import run_worker_bundle
from .workflow_registry import list_workflows, show_workflow, workflow_env_exports


def _csv(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {item.strip() for item in value.split(",") if item.strip()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="auto-video")
    sub = parser.add_subparsers(dest="command", required=False)

    init = sub.add_parser("init")
    init.add_argument("project", nargs="?")
    init.add_argument("--template", default="demo")
    init.add_argument("--list-templates", action="store_true")
    init.add_argument("--force", action="store_true")

    validate = sub.add_parser("validate")
    validate.add_argument("project")

    images = sub.add_parser("images")
    images.add_argument("project")
    images.add_argument("--dry-run", action="store_true")
    images.add_argument("--provider")
    images.add_argument("--only")
    images.add_argument("--failed-only", action="store_true")
    images.add_argument("--skip-succeeded", action="store_true")

    generate = sub.add_parser("generate")
    generate.add_argument("project")
    generate.add_argument("--dry-run", action="store_true")
    generate.add_argument("--provider")
    generate.add_argument("--only")
    generate.add_argument("--failed-only", action="store_true")
    generate.add_argument("--skip-succeeded", action="store_true")

    audio = sub.add_parser("audio")
    audio.add_argument("project")
    audio.add_argument("--dry-run", action="store_true")
    audio.add_argument("--provider")
    audio.add_argument("--only")
    audio.add_argument("--failed-only", action="store_true")
    audio.add_argument("--skip-succeeded", action="store_true")

    assemble = sub.add_parser("assemble")
    assemble.add_argument("project")
    assemble.add_argument("--dry-run", action="store_true")

    probe = sub.add_parser("probe")
    probe.add_argument("project")
    probe.add_argument("--dry-run", action="store_true")
    probe.add_argument("--strict", action="store_true")
    probe.add_argument("--ffprobe", default="ffprobe")
    probe.add_argument("--ffmpeg", default="ffmpeg")
    probe.add_argument("--min-duration-ratio", type=float, default=0.8)
    probe.add_argument("--blackdetect", action="store_true")
    probe.add_argument("--max-black-ratio", type=float, default=0.98)

    continuity = sub.add_parser("continuity")
    continuity_sub = continuity.add_subparsers(dest="continuity_command")
    continuity_extract = continuity_sub.add_parser("extract-tail-frames")
    continuity_extract.add_argument("project")
    continuity_extract.add_argument("--dry-run", action="store_true")
    continuity_extract.add_argument("--force", action="store_true")

    jobs = sub.add_parser("jobs")
    jobs_sub = jobs.add_subparsers(dest="jobs_command")

    jobs_plan = jobs_sub.add_parser("plan")
    jobs_plan.add_argument("project")
    jobs_plan.add_argument("--provider")
    jobs_plan.add_argument("--kind", choices=["image", "video", "audio", "lipsync"], default="video")
    jobs_plan.add_argument("--only")
    jobs_plan.add_argument("--failed-only", action="store_true")
    jobs_plan.add_argument("--skip-succeeded", action="store_true")

    jobs_submit = jobs_sub.add_parser("submit")
    jobs_submit.add_argument("project")
    jobs_submit.add_argument("--provider")
    jobs_submit.add_argument("--kind", choices=["image", "video", "audio", "lipsync"], default="video")
    jobs_submit.add_argument("--only")
    jobs_submit.add_argument("--failed-only", action="store_true")
    jobs_submit.add_argument("--skip-succeeded", action="store_true")

    jobs_status = jobs_sub.add_parser("status")
    jobs_status.add_argument("project")

    worker = sub.add_parser("worker")
    worker_sub = worker.add_subparsers(dest="worker_command")

    worker_export = worker_sub.add_parser("export")
    worker_export.add_argument("project")
    worker_export.add_argument("--provider")
    worker_export.add_argument("--kind", choices=["image", "video", "audio", "lipsync"], default="video")
    worker_export.add_argument("--only")
    worker_export.add_argument("--failed-only", action="store_true")
    worker_export.add_argument("--skip-succeeded", action="store_true")
    worker_export.add_argument("--out", required=True)
    worker_export.add_argument("--force", action="store_true")

    worker_run = worker_sub.add_parser("run")
    worker_run.add_argument("bundle")

    worker_import = worker_sub.add_parser("import")
    worker_import.add_argument("project")
    worker_import.add_argument("bundle")

    remote = sub.add_parser("remote")
    remote_sub = remote.add_subparsers(dest="remote_command")

    remote_run = remote_sub.add_parser("run")
    remote_run.add_argument("project")
    remote_run.add_argument("--profile")
    remote_run.add_argument("--host")
    remote_run.add_argument("--remote-dir")
    remote_run.add_argument("--provider")
    remote_run.add_argument("--kind", choices=["image", "video", "audio", "lipsync"], default="video")
    remote_run.add_argument("--only")
    remote_run.add_argument("--failed-only", action="store_true")
    remote_run.add_argument("--skip-succeeded", action="store_true")
    remote_run.add_argument("--local-dir")
    remote_run.add_argument("--remote-auto-video")
    remote_run.add_argument("--ssh-option", action="append", default=[])
    remote_run.add_argument("--rsync-option", action="append", default=[])
    remote_run.add_argument("--remote-env", action="append", default=[])
    remote_run.add_argument("--dry-run", action="store_true")

    remote_profiles = remote_sub.add_parser("profiles")
    remote_profiles.add_argument("project")

    remote_doctor = remote_sub.add_parser("doctor")
    remote_doctor.add_argument("--host", required=True)
    remote_doctor.add_argument("--remote-dir", required=True)
    remote_doctor.add_argument("--remote-auto-video", default="auto-video")
    remote_doctor.add_argument("--ssh-option", action="append", default=[])
    remote_doctor.add_argument("--dry-run", action="store_true")

    remote_wrapup = remote_sub.add_parser("wrapup")
    remote_wrapup.add_argument("--host", required=True)
    remote_wrapup.add_argument("--remote-dir", required=True)
    remote_wrapup.add_argument("--ssh-option", action="append", default=[])
    remote_wrapup.add_argument("--comfyui-base-url", default="http://127.0.0.1:6006")
    remote_wrapup.add_argument("--dry-run", action="store_true")

    providers = sub.add_parser("providers")
    providers_sub = providers.add_subparsers(dest="providers_command")
    providers_sub.add_parser("health")

    workflows = sub.add_parser("workflows")
    workflows_sub = workflows.add_subparsers(dest="workflows_command")
    workflows_list = workflows_sub.add_parser("list")
    workflows_list.add_argument("project")
    workflows_show = workflows_sub.add_parser("show")
    workflows_show.add_argument("project")
    workflows_show.add_argument("name")
    workflows_env = workflows_sub.add_parser("env")
    workflows_env.add_argument("project")
    workflows_env.add_argument("name")

    web = sub.add_parser("web")
    web.add_argument("--workspace", default="web_projects")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--token")
    web.add_argument("--token-env", default="AUTO_VIDEO_WEB_TOKEN")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    try:
        if args.command is None:
            parser.print_help()
            return 0
        if args.command == "init":
            if args.list_templates:
                print(json.dumps({"templates": list_templates()}, ensure_ascii=False, indent=2))
                return 0
            if not args.project:
                print("ConfigError: init requires a project path unless --list-templates is set")
                return 1
            init_project(Path(args.project), template_name=args.template, force=args.force)
            return 0
        if args.command == "validate":
            validate_project(load_project(args.project))
            return 0
        if args.command == "images":
            result = generate_images(
                load_project(args.project),
                provider_name=args.provider,
                dry_run=args.dry_run,
                only=_csv(args.only),
                failed_only=args.failed_only,
                skip_succeeded=args.skip_succeeded,
            )
            if args.dry_run:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "generate":
            result = generate_videos(
                load_project(args.project),
                provider_name=args.provider,
                dry_run=args.dry_run,
                only=_csv(args.only),
                failed_only=args.failed_only,
                skip_succeeded=args.skip_succeeded,
            )
            if args.dry_run:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "audio":
            result = generate_audio(
                load_project(args.project),
                provider_name=args.provider,
                dry_run=args.dry_run,
                only=_csv(args.only),
                failed_only=args.failed_only,
                skip_succeeded=args.skip_succeeded,
            )
            if args.dry_run:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "assemble":
            result = assemble_project(load_project(args.project), dry_run=args.dry_run)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "probe":
            report = probe_project(
                load_project(args.project),
                dry_run=args.dry_run,
                ffprobe=args.ffprobe,
                ffmpeg=args.ffmpeg,
                min_duration_ratio=args.min_duration_ratio,
                blackdetect=args.blackdetect,
                max_black_ratio=args.max_black_ratio,
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1 if args.strict and report["summary"]["failed"] > 0 else 0
        if args.command == "continuity" and args.continuity_command == "extract-tail-frames":
            result = extract_tail_frames(load_project(args.project), dry_run=args.dry_run, force=args.force)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "jobs" and args.jobs_command == "plan":
            result = plan_jobs(
                load_project(args.project),
                kind=args.kind,
                provider_name=args.provider,
                only=_csv(args.only),
                failed_only=args.failed_only,
                skip_succeeded=args.skip_succeeded,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "jobs" and args.jobs_command == "submit":
            project = load_project(args.project)
            results = submit_jobs(
                project,
                kind=args.kind,
                provider_name=args.provider,
                only=_csv(args.only),
                failed_only=args.failed_only,
                skip_succeeded=args.skip_succeeded,
            )
            print(
                json.dumps(
                    {"submitted": [result.job_id for result in results], "count": len(results)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "jobs" and args.jobs_command == "status":
            project = load_project(args.project)
            store = JobStore(project.config.root / "manifest.json", project_name=project.config.name)
            print(json.dumps(store.summary(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "worker" and args.worker_command == "export":
            result = export_worker_bundle(
                load_project(args.project),
                Path(args.out),
                kind=args.kind,
                provider_name=args.provider,
                only=_csv(args.only),
                failed_only=args.failed_only,
                skip_succeeded=args.skip_succeeded,
                force=args.force,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "worker" and args.worker_command == "run":
            result = run_worker_bundle(Path(args.bundle))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "worker" and args.worker_command == "import":
            result = import_worker_results(Path(args.project), Path(args.bundle))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "remote" and args.remote_command == "run":
            project = load_project(args.project)
            result = run_remote_worker(
                project,
                build_remote_run_options_from_profile(
                    project,
                    profile_name=args.profile,
                    host=args.host,
                    remote_dir=args.remote_dir,
                    provider_name=args.provider,
                    kind=args.kind,
                    only=_csv(args.only),
                    failed_only=args.failed_only,
                    skip_succeeded=args.skip_succeeded,
                    local_dir=Path(args.local_dir) if args.local_dir else None,
                    remote_auto_video=args.remote_auto_video,
                    ssh_options=tuple(args.ssh_option),
                    rsync_options=tuple(args.rsync_option),
                    remote_env=tuple(args.remote_env),
                ),
                dry_run=args.dry_run,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "remote" and args.remote_command == "profiles":
            project = load_project(args.project)
            print(json.dumps({"profiles": list_remote_profiles(project)}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "remote" and args.remote_command == "doctor":
            result = run_remote_doctor(
                RemoteDoctorOptions(
                    host=args.host,
                    remote_dir=args.remote_dir,
                    remote_auto_video=args.remote_auto_video,
                    ssh_options=tuple(args.ssh_option),
                ),
                dry_run=args.dry_run,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 1
        if args.command == "remote" and args.remote_command == "wrapup":
            result = run_remote_wrapup(
                RemoteWrapupOptions(
                    host=args.host,
                    remote_dir=args.remote_dir,
                    ssh_options=tuple(args.ssh_option),
                    comfyui_base_url=args.comfyui_base_url,
                ),
                dry_run=args.dry_run,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 1
        if args.command == "providers" and args.providers_command == "health":
            print(json.dumps({"mock": "ok"}, indent=2))
            return 0
        if args.command == "workflows" and args.workflows_command == "list":
            print(json.dumps({"workflows": list_workflows(load_project(args.project))}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "workflows" and args.workflows_command == "show":
            print(json.dumps(show_workflow(load_project(args.project), args.name), ensure_ascii=False, indent=2))
            return 0
        if args.command == "workflows" and args.workflows_command == "env":
            exports = workflow_env_exports(load_project(args.project), args.name)
            print(json.dumps({"profile": args.name, "env": exports}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "web":
            run_web_server(Path(args.workspace), host=args.host, port=args.port, token=args.token, token_env=args.token_env)
            return 0
        parser.print_help()
        return 2
    except AutoVideoError as exc:
        print(str(exc))
        return 1


def entrypoint() -> int:
    return main()
