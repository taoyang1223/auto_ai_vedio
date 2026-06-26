from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="auto-video")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init")
    sub.add_parser("validate")
    sub.add_parser("images")
    sub.add_parser("generate")
    sub.add_parser("assemble")
    sub.add_parser("probe")
    providers = sub.add_parser("providers")
    providers.add_subparsers(dest="providers_command").add_parser("health")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def entrypoint() -> int:
    return main()
