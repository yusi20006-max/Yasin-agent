"""Multi-agent collaboration harness for Yasin-Agent (Issue #27).

This module owns orchestration only. Tool authorization remains external to
Yasin-Agent (Yasin-MCP), and YasinHub can consume the structured events later.
Workers receive independent execution/session identities and copies of task
context; no credential or authorization state is shared between workers.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .execution import ExecutionEvent, ExecutionEventType, ExecutionRecord, ExecutionRuntime


WorkerCallable = Callable[[Mapping[str, Any], ExecutionRecord], Any]


@dataclass(frozen=True)
class WorkerSpec:
    """Definition of one isolated worker in a collaboration task."""

    worker_id: str
    runner: WorkerCallable
    agent_id: Optional[str] = None
    capabilities: Sequence[str] = field(default_factory=tuple)
    workspace: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkerResult:
    """Deterministic result envelope for one worker."""

    worker_id: str
    status: str
    result: Any = None
    error: Optional[str] = None
    execution_id: str = ""
    session_id: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "execution_id": self.execution_id,
            "session_id": self.session_id,
        }


@dataclass(frozen=True)
class CollaborationResult:
    """Parent-task aggregation, with workers ordered by worker_id."""

    task_id: str
    status: str
    workers: tuple[WorkerResult, ...]

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "workers": [worker.as_dict() for worker in self.workers],
        }


class CollaborationHarness:
    """Run isolated Yasin-Agent workers concurrently with bounded concurrency."""

    def __init__(
        self,
        *,
        runtime: Optional[ExecutionRuntime] = None,
        max_concurrent_workers: int = 4,
    ) -> None:
        if max_concurrent_workers < 1:
            raise ValueError("max_concurrent_workers must be >= 1")
        self.runtime = runtime or ExecutionRuntime()
        self.max_concurrent_workers = max_concurrent_workers
        self._workers: Dict[str, WorkerSpec] = {}
        self._cancellations: Dict[str, threading.Event] = {}
        self._executions: Dict[str, Dict[str, str]] = {}
        self._lock = threading.RLock()

    @property
    def events(self):
        """The underlying execution event emitter for YasinHub observation."""
        return self.runtime.events

    def register_worker(self, worker: WorkerSpec) -> None:
        if not worker.worker_id:
            raise ValueError("worker_id must not be empty")
        with self._lock:
            if worker.worker_id in self._workers:
                raise ValueError(f"worker_id already registered: {worker.worker_id}")
            self._workers[worker.worker_id] = worker

    def register(
        self,
        worker_id: str,
        runner: WorkerCallable,
        *,
        agent_id: Optional[str] = None,
        capabilities: Sequence[str] = (),
        workspace: Any = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> WorkerSpec:
        worker = WorkerSpec(
            worker_id=worker_id,
            runner=runner,
            agent_id=agent_id,
            capabilities=tuple(capabilities),
            workspace=workspace,
            metadata=dict(metadata or {}),
        )
        self.register_worker(worker)
        return worker

    def unregister_worker(self, worker_id: str) -> None:
        with self._lock:
            self._workers.pop(worker_id)

    def workers(self) -> List[WorkerSpec]:
        with self._lock:
            return [self._workers[key] for key in sorted(self._workers)]

    def cancel(self, task_id: str) -> None:
        """Request cooperative cancellation for all active workers of a task."""
        with self._lock:
            signal = self._cancellations.get(task_id)
            execution_ids = list(self._executions.get(task_id, {}).values())
        if signal is not None:
            signal.set()
        for execution_id in execution_ids:
            record = self.runtime.get(execution_id)
            if record is not None and not record.is_terminal():
                self.runtime.cancel(execution_id)

    def run(
        self,
        task_id: str,
        *,
        context: Optional[Mapping[str, Any]] = None,
        worker_ids: Optional[Sequence[str]] = None,
        max_concurrent_workers: Optional[int] = None,
    ) -> CollaborationResult:
        """Run selected workers and aggregate results deterministically."""
        with self._lock:
            selected_ids = list(worker_ids) if worker_ids is not None else list(self._workers)
            unknown = sorted(set(selected_ids) - set(self._workers))
            if unknown:
                raise KeyError(f"unknown workers: {unknown}")
            if task_id in self._cancellations:
                raise ValueError(f"task_id already active: {task_id}")
            self._cancellations[task_id] = threading.Event()
            self._executions[task_id] = {}
            specs = [self._workers[worker_id] for worker_id in selected_ids]

        limit = max_concurrent_workers or self.max_concurrent_workers
        if limit < 1:
            raise ValueError("max_concurrent_workers must be >= 1")
        limit = min(limit, max(1, len(specs)))
        parent_context = dict(context or {})
        results: Dict[str, WorkerResult] = {}

        def execute(spec: WorkerSpec) -> WorkerResult:
            signal = self._cancellations[task_id]
            execution = self.runtime.create(
                task_id=task_id,
                agent_id=spec.agent_id or spec.worker_id,
                workspace=spec.workspace,
                capabilities=tuple(spec.capabilities),
                metadata={**dict(parent_context), **dict(spec.metadata), "worker_id": spec.worker_id},
            )
            with self._lock:
                self._executions[task_id][spec.worker_id] = execution.execution_id
            self.runtime.events.emit(
                "worker.registered",
                execution_id=execution.execution_id,
                task_id=task_id,
                session_id=execution.session_id,
                status=execution.status.value,
                agent_id=execution.agent_id,
                workspace_id=execution.workspace.workspace_id,
                metadata={"worker_id": spec.worker_id},
            )
            if signal.is_set() or execution.cancel_requested:
                self.runtime.cancel(execution.execution_id)
                return WorkerResult(spec.worker_id, "cancelled", execution_id=execution.execution_id, session_id=execution.session_id)

            self.runtime.start(execution.execution_id)
            # A fresh mapping prevents one worker from mutating another worker's context.
            worker_context = dict(parent_context)
            worker_context.update(dict(spec.metadata))
            worker_context["worker_id"] = spec.worker_id
            worker_context["task_id"] = task_id
            worker_context["cancellation_requested"] = signal.is_set
            try:
                value = spec.runner(worker_context, execution)
                if signal.is_set() or execution.cancel_requested:
                    if not execution.is_terminal():
                        self.runtime.cancel(execution.execution_id)
                    return WorkerResult(spec.worker_id, "cancelled", execution_id=execution.execution_id, session_id=execution.session_id)
                self.runtime.complete(execution.execution_id, value)
                return WorkerResult(spec.worker_id, "succeeded", result=value, execution_id=execution.execution_id, session_id=execution.session_id)
            except Exception as exc:  # noqa: BLE001 - worker failures are isolated by design
                error = str(exc)
                self.runtime.fail(execution.execution_id, error)
                return WorkerResult(spec.worker_id, "failed", error=error, execution_id=execution.execution_id, session_id=execution.session_id)

        try:
            with ThreadPoolExecutor(max_workers=limit, thread_name_prefix="yasin-worker") as pool:
                futures: Dict[Future[WorkerResult], str] = {
                    pool.submit(execute, spec): spec.worker_id for spec in specs
                }
                for future in as_completed(futures):
                    worker_id = futures[future]
                    try:
                        results[worker_id] = future.result()
                    except Exception as exc:  # defensive: execute isolates ordinary worker errors
                        results[worker_id] = WorkerResult(worker_id, "failed", error=str(exc))
        finally:
            with self._lock:
                self._cancellations.pop(task_id, None)
                self._executions.pop(task_id, None)

        ordered = tuple(results[key] for key in sorted(results))
        if any(worker.status == "failed" for worker in ordered):
            status = "completed_with_failures"
        elif any(worker.status == "cancelled" for worker in ordered):
            status = "cancelled"
        else:
            status = "succeeded"
        return CollaborationResult(task_id=task_id, status=status, workers=ordered)


__all__ = [
    "CollaborationHarness",
    "CollaborationResult",
    "WorkerResult",
    "WorkerSpec",
]
