#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.exists():
    sys.path.insert(0, SRC.as_posix())

from auto_video.wan_remote_smoke import (
    WanRemoteSmokeOptions,
    build_wan_remote_smoke_plan,
    execute_wan_remote_smoke,
)


def main() -> int:
    args = build_parser().parse_args()
    options = WanRemoteSmokeOptions(
        project=Path(args.project),
        host=args.host,
        remote_dir=args.remote_dir,
        wan_base_url=args.wan_base_url,
        wan_base_url_env=args.wan_base_url_env,
        wan_token_env=args.wan_token_env,
        provider=args.provider,
        kind=args.kind,
        only=args.only,
        local_dir=Path(args.local_dir) if args.local_dir else None,
        remote_auto_video=args.remote_auto_video,
        remote_python=args.remote_python,
        remote_wan_doctor=args.remote_wan_doctor,
        require_i2v=args.require_i2v,
        require_t2v=args.require_t2v,
        ssh_options=tuple(args.ssh_option),
    )
    if args.execute:
        result = execute_wan_remote_smoke(options)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    plan = build_wan_remote_smoke_plan(options)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan or execute a Wan remote GPU smoke workflow")
    parser.add_argument("--project", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--remote-dir", required=True)
    parser.add_argument("--wan-base-url", required=True)
    parser.add_argument("--wan-base-url-env", default="WAN_BASE_URL")
    parser.add_argument("--wan-token-env")
    parser.add_argument("--provider", default="wan_http")
    parser.add_argument("--kind", choices=["image", "video", "audio"], default="video")
    parser.add_argument("--only")
    parser.add_argument("--local-dir")
    parser.add_argument("--remote-auto-video", default="auto-video")
    parser.add_argument("--remote-python", default="python")
    parser.add_argument("--remote-wan-doctor", default="auto_video.wan_runtime_doctor")
    parser.add_argument("--require-i2v", action="store_true")
    parser.add_argument("--require-t2v", action="store_true")
    parser.add_argument("--ssh-option", action="append", default=[])
    parser.add_argument("--execute", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
