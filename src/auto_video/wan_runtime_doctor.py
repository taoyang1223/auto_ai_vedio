from __future__ import annotations

import argparse
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> int:
    args = build_parser().parse_args()
    report = run(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Wan HTTP runtime preflight doctor")
    parser.add_argument("--base-url")
    parser.add_argument("--base-url-env")
    parser.add_argument("--token-env")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--require-i2v", action="store_true")
    parser.add_argument("--require-t2v", action="store_true")
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    base_url, base_url_check = _resolve_base_url(args)
    if not base_url:
        return _report("", [base_url_check])

    checks = [base_url_check]
    health = _fetch_health(base_url, token=_token(args), timeout=args.timeout)
    checks.append(health)
    details = health.get("details", {}) if health["status"] == "ok" else {}
    if args.require_i2v:
        checks.append(_capability_check("i2v_loaded", details, "I2V model is loaded", "Load the Wan I2V model."))
    if args.require_t2v:
        checks.append(_capability_check("t2v_loaded", details, "T2V model is loaded", "Load the Wan T2V model."))
    return _report(base_url, checks)


def _resolve_base_url(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    if args.base_url:
        return args.base_url.rstrip("/"), _check("base_url", "ok", "base URL provided")
    if args.base_url_env:
        value = os.environ.get(args.base_url_env, "")
        if value:
            return value.rstrip("/"), _check("base_url", "ok", f"base URL read from {args.base_url_env}")
        return "", _check(
            "base_url",
            "failed",
            f"environment variable {args.base_url_env} is not set",
            fix="Set the environment variable or pass --base-url.",
        )
    return "", _check(
        "base_url",
        "failed",
        "base URL is required",
        fix="Pass --base-url or --base-url-env.",
    )


def _token(args: argparse.Namespace) -> str:
    if not args.token_env:
        return ""
    return os.environ.get(args.token_env, "")


def _fetch_health(base_url: str, *, token: str, timeout: int) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"{base_url}/health", headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return _check(
            "health",
            "failed",
            f"Wan health endpoint returned HTTP {exc.code}",
            fix=body or "Check the Wan service logs.",
        )
    except URLError as exc:
        return _check(
            "health",
            "failed",
            f"Wan health request failed: {exc.reason}",
            fix="Check base URL, SSH tunnel, firewall, and whether the Wan server is running.",
        )
    except TimeoutError:
        return _check(
            "health",
            "failed",
            f"Wan health request timed out after {timeout} seconds",
            fix="Check service load, GPU startup, and network connectivity.",
        )

    if "application/json" not in content_type:
        return _check(
            "health",
            "failed",
            f"Wan health endpoint returned non-JSON content type {content_type!r}",
            fix="Verify the base URL points to the Wan HTTP service.",
        )
    try:
        details = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        return _check("health", "failed", f"Wan health JSON could not be parsed: {exc}", fix="Check server output.")

    status = str(details.get("status", "")).lower()
    if status not in {"ok", "ready", "healthy"}:
        return _check(
            "health",
            "failed",
            f"Wan health status is {details.get('status')!r}",
            fix="Wait for model loading to finish or inspect the Wan service logs.",
            details=details,
        )
    return _check("health", "ok", "Wan health endpoint responded", details=details)


def _capability_check(name: str, details: dict[str, Any], ok_message: str, fix: str) -> dict[str, Any]:
    if details.get(name) is True:
        return _check(name, "ok", ok_message)
    return _check(name, "failed", f"{name} is not ready", fix=fix, details={name: details.get(name)})


def _check(
    name: str,
    status: str,
    message: str,
    *,
    fix: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name, "status": status, "message": message}
    if fix:
        payload["fix"] = fix
    if details is not None:
        payload["details"] = details
    return payload


def _report(base_url: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": all(check["status"] != "failed" for check in checks),
        "base_url": base_url,
        "checks": checks,
    }


if __name__ == "__main__":
    raise SystemExit(main())
