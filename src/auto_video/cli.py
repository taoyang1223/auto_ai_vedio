from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .errors import AutoVideoError
from .job_store import JobStore
from .pipeline import generate_images, generate_videos, plan_jobs, submit_jobs
from .probe import probe_project
from .project import load_project
from .render import build_render_plan
from .validation import validate_project
from .worker_bundle import export_worker_bundle, import_worker_results
from .worker_runner import run_worker_bundle


PROJECT_YAML = """name: demo_ad
aspect_ratio: "9:16"
width: 1080
height: 1920
fps: 30
default_video_provider: mock
default_image_provider: mock
default_audio_provider: mock
render:
  transition:
    type: fade
    duration: 0.6
  bgm_volume: 0.2
  subtitle_style: default
  brand:
    text: "Demo Brand"
    at: 1.2
  cta:
    text: "Click for more"
    at: 2.6
"""

SHOTS_JSON = """{
  "shots": [
    {
      "id": "S01",
      "title": "Hook",
      "duration": 5,
      "intent": "Show fatigue and introduce the product need",
      "provider": "mock",
      "visual_prompt": "A tired person at a cold desk",
      "camera_motion": "slow_dolly_in",
      "environment_motion": "screen flicker, dust floats",
      "performance": "tired breathing, shoulders drop slightly",
      "lighting": "cold fluorescent light",
      "audio_intent": "quiet room tone",
      "subtitle": "Late night again",
      "negative_prompt": "text, watermark",
      "refs": [
        {
          "path": "assets/refs/S01.txt",
          "type": "text",
          "role": "first_frame",
          "usage": "preserve_subject"
        }
      ]
    }
  ]
}
"""


def _csv(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {item.strip() for item in value.split(",") if item.strip()}


def init_project(path: Path) -> None:
    (path / "assets" / "refs").mkdir(parents=True, exist_ok=True)
    (path / "generated" / "images").mkdir(parents=True, exist_ok=True)
    (path / "generated" / "clips").mkdir(parents=True, exist_ok=True)
    (path / "generated" / "audio").mkdir(parents=True, exist_ok=True)
    (path / "renders").mkdir(parents=True, exist_ok=True)
    (path / "reports").mkdir(parents=True, exist_ok=True)
    (path / "project.yaml").write_text(PROJECT_YAML, encoding="utf-8")
    (path / "shots.json").write_text(SHOTS_JSON, encoding="utf-8")
    (path / "assets" / "refs" / "S01.txt").write_text("mock first-frame reference\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="auto-video")
    sub = parser.add_subparsers(dest="command", required=False)

    init = sub.add_parser("init")
    init.add_argument("project")

    validate = sub.add_parser("validate")
    validate.add_argument("project")

    images = sub.add_parser("images")
    images.add_argument("project")
    images.add_argument("--dry-run", action="store_true")
    images.add_argument("--provider")
    images.add_argument("--only")

    generate = sub.add_parser("generate")
    generate.add_argument("project")
    generate.add_argument("--dry-run", action="store_true")
    generate.add_argument("--provider")
    generate.add_argument("--only")

    assemble = sub.add_parser("assemble")
    assemble.add_argument("project")
    assemble.add_argument("--dry-run", action="store_true")

    probe = sub.add_parser("probe")
    probe.add_argument("project")
    probe.add_argument("--dry-run", action="store_true")

    jobs = sub.add_parser("jobs")
    jobs_sub = jobs.add_subparsers(dest="jobs_command")

    jobs_plan = jobs_sub.add_parser("plan")
    jobs_plan.add_argument("project")
    jobs_plan.add_argument("--provider")
    jobs_plan.add_argument("--kind", choices=["image", "video", "audio"], default="video")
    jobs_plan.add_argument("--only")

    jobs_submit = jobs_sub.add_parser("submit")
    jobs_submit.add_argument("project")
    jobs_submit.add_argument("--provider")
    jobs_submit.add_argument("--kind", choices=["image", "video", "audio"], default="video")
    jobs_submit.add_argument("--only")

    jobs_status = jobs_sub.add_parser("status")
    jobs_status.add_argument("project")

    worker = sub.add_parser("worker")
    worker_sub = worker.add_subparsers(dest="worker_command")

    worker_export = worker_sub.add_parser("export")
    worker_export.add_argument("project")
    worker_export.add_argument("--provider")
    worker_export.add_argument("--kind", choices=["image", "video", "audio"], default="video")
    worker_export.add_argument("--only")
    worker_export.add_argument("--out", required=True)
    worker_export.add_argument("--force", action="store_true")

    worker_run = worker_sub.add_parser("run")
    worker_run.add_argument("bundle")

    worker_import = worker_sub.add_parser("import")
    worker_import.add_argument("project")
    worker_import.add_argument("bundle")

    providers = sub.add_parser("providers")
    providers_sub = providers.add_subparsers(dest="providers_command")
    providers_sub.add_parser("health")
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
            init_project(Path(args.project))
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
            )
            if args.dry_run:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "assemble":
            plan = build_render_plan(load_project(args.project))
            if args.dry_run:
                print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0
        if args.command == "probe":
            report = probe_project(load_project(args.project), dry_run=args.dry_run)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        if args.command == "jobs" and args.jobs_command == "plan":
            result = plan_jobs(
                load_project(args.project),
                kind=args.kind,
                provider_name=args.provider,
                only=_csv(args.only),
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
        if args.command == "providers" and args.providers_command == "health":
            print(json.dumps({"mock": "ok"}, indent=2))
            return 0
        parser.print_help()
        return 2
    except AutoVideoError as exc:
        print(str(exc))
        return 1


def entrypoint() -> int:
    return main()
