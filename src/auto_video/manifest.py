from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import AssetResult


class ManifestStore:
    def __init__(self, path: Path, *, project_name: str):
        self.path = path
        self.root = path.parent.resolve()
        if path.exists():
            self.data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.data = {
                "project": project_name,
                "schema_version": "0.1",
                "assets": {},
                "shots": {},
                "renders": {},
            }
        self.data.setdefault("project", project_name)
        self.data.setdefault("schema_version", "0.1")
        self.data.setdefault("assets", {})
        self.data.setdefault("shots", {})
        self.data.setdefault("renders", {})

    def _relative(self, value: Path) -> str:
        try:
            return value.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return value.as_posix()

    def record_asset(self, result: AssetResult) -> None:
        shot = self.data["shots"].setdefault(result.shot_id, {})
        shot["status"] = result.status
        shot["provider"] = result.provider
        if result.kind == "image":
            shot["image"] = self._relative(result.path)
        elif result.kind == "clip":
            shot["clip"] = self._relative(result.path)
        elif result.kind == "audio":
            shot["audio"] = self._relative(result.path)
        else:
            self.data["assets"][f"{result.shot_id}:{result.kind}"] = self._relative(result.path)
        if result.duration is not None:
            shot["duration"] = result.duration
        if result.error is not None:
            shot["error"] = result.error
        if result.retryable:
            shot["retryable"] = True

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.data, ensure_ascii=False, indent=2) + "\n"
        self.path.write_text(payload, encoding="utf-8")
