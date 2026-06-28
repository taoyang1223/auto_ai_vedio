from __future__ import annotations

import threading
import traceback
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Empty, Queue
from typing import Any
from uuid import uuid4

from .errors import AutoVideoError


TaskLogger = Callable[[str], None]
TaskRunner = Callable[[TaskLogger], Any]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class WebTask:
    id: str
    project: str
    action: str
    label: str
    payload: dict[str, Any]
    status: str = "queued"
    created_at: str = field(default_factory=utc_now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    fix: str | None = None
    result: Any = None
    cancel_requested: bool = False
    logs: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self, *, include_result: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "project": self.project,
            "action": self.action,
            "label": self.label,
            "payload": self.payload,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "fix": self.fix,
            "cancel_requested": self.cancel_requested,
            "logs": list(self.logs),
        }
        if include_result:
            data["result"] = self.result
        return data


class WebTaskQueue:
    def __init__(self, *, max_history: int = 80) -> None:
        self._max_history = max_history
        self._ids: Queue[str] = Queue()
        self._tasks: dict[str, WebTask] = {}
        self._runners: dict[str, TaskRunner] = {}
        self._history: deque[str] = deque()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def enqueue(
        self,
        *,
        project: str,
        action: str,
        label: str,
        payload: dict[str, Any],
        runner: TaskRunner,
    ) -> dict[str, Any]:
        task = WebTask(id=uuid4().hex[:12], project=project, action=action, label=label, payload=payload)
        with self._lock:
            self._tasks[task.id] = task
            self._runners[task.id] = runner
            self._history.appendleft(task.id)
            self._trim_locked()
            self._ensure_worker_locked()
        self._add_log(task.id, "任务已进入队列")
        self._ids.put(task.id)
        return task.to_dict()

    def list(self, *, project: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            tasks = [self._tasks[task_id] for task_id in self._history if task_id in self._tasks]
            if project is not None:
                tasks = [task for task in tasks if task.project == project]
            return [task.to_dict(include_result=False) for task in tasks]

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return task.to_dict() if task else None

    def cancel(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            if task.status == "queued":
                task.cancel_requested = True
                task.status = "canceled"
                task.finished_at = utc_now_iso()
                self._runners.pop(task_id, None)
                task.logs.append({"at": utc_now_iso(), "message": "任务已取消"})
            elif task.status == "running" and not task.cancel_requested:
                task.cancel_requested = True
                task.logs.append({"at": utc_now_iso(), "message": "已请求暂停/取消；当前运行步骤结束后生效"})
            return task.to_dict()

    def _ensure_worker_locked(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._run_forever, name="auto-video-web-task-worker", daemon=True)
        self._worker.start()

    def _run_forever(self) -> None:
        while True:
            try:
                task_id = self._ids.get(timeout=1)
            except Empty:
                continue
            try:
                self._run_one(task_id)
            finally:
                self._ids.task_done()

    def _run_one(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            runner = self._runners.pop(task_id, None)
            if task is None or runner is None or task.status == "canceled":
                return
            task.status = "running"
            task.started_at = utc_now_iso()
            task.logs.append({"at": utc_now_iso(), "message": "任务开始执行"})
        try:
            result = runner(lambda message: self._add_log(task_id, message))
        except AutoVideoError as exc:
            with self._lock:
                task.status = "failed"
                task.error = exc.message
                task.fix = exc.fix
                task.finished_at = utc_now_iso()
                task.logs.append({"at": utc_now_iso(), "message": f"任务失败：{exc.message}"})
        except Exception as exc:
            with self._lock:
                task.status = "failed"
                task.error = str(exc)
                task.fix = "查看任务日志并检查项目配置。"
                task.finished_at = utc_now_iso()
                task.logs.append({"at": utc_now_iso(), "message": f"任务异常：{exc}"})
                task.logs.append({"at": utc_now_iso(), "message": traceback.format_exc(limit=8).strip()})
        else:
            with self._lock:
                task.status = "succeeded"
                task.result = result
                task.finished_at = utc_now_iso()
                task.logs.append({"at": utc_now_iso(), "message": "任务执行完成"})

    def _add_log(self, task_id: str, message: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None:
                task.logs.append({"at": utc_now_iso(), "message": message})

    def _trim_locked(self) -> None:
        while len(self._history) > self._max_history:
            task_id = self._history.pop()
            task = self._tasks.get(task_id)
            if task and task.status in {"queued", "running"}:
                self._history.appendleft(task_id)
                break
            self._tasks.pop(task_id, None)
            self._runners.pop(task_id, None)
