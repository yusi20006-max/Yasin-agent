"""Parallel worker fleet orchestration for Issue #28.

Yasin-Agent owns orchestration and observation contracts. Tool governance
remains in Yasin-MCP and presentation/control remains in YasinHub.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .execution import ExecutionRecord, ExecutionRuntime
from .harness import CollaborationHarness, CollaborationResult

FleetWorkerCallable = Callable[[Mapping[str, Any], ExecutionRecord], Any]


@dataclass(frozen=True)
class FleetWorkerPlan:
    """Explicit bounded definition of one fleet worker."""

    worker_id: str
    role: str
    objective: str
    runner: FleetWorkerCallable
    workspace: Any = None
    capabilities: Sequence[str] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    agent_id: Optional[str] = None


@dataclass(frozen=True)
class FleetWorkerStatus:
    worker_id: str
    role: str
    objective: str
    status: str
    execution_id: str = ""
    session_id: str = ""
    error: Optional[str] = None
    result: Any = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "role": self.role,
            "objective": self.objective,
            "status": self.status,
            "execution_id": self.execution_id,
            "session_id": self.session_id,
            "error": self.error,
            "result": self.result,
        }


@dataclass(frozen=True)
class FleetStatus:
    task_id: str
    status: str
    workers: tuple[FleetWorkerStatus, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "workers": [worker.as_dict() for worker in self.workers],
        }


class WorkerFleet:
    """Coordinate a bounded fleet of independent Yasin-Agent workers."""

    def __init__(self, *, runtime: Optional[ExecutionRuntime] = None, max_workers: int = 8, max_concurrent_workers: int = 4) -> None:
        if max_workers < 1 or max_concurrent_workers < 1:
            raise ValueError("worker limits must be >= 1")
        if max_concurrent_workers > max_workers:
            raise ValueError("max_concurrent_workers cannot exceed max_workers")
        self.runtime = runtime or ExecutionRuntime()
        self.max_workers = max_workers
        self.max_concurrent_workers = max_concurrent_workers
        self._plans: Dict[str, FleetWorkerPlan] = {}
        self._statuses: Dict[str, Dict[str, FleetWorkerStatus]] = {}
        self._tasks: Dict[str, CollaborationHarness] = {}
        self._task_status: Dict[str, str] = {}
        self._lock = threading.RLock()

    @property
    def events(self):
        return self.runtime.events

    def register(self, plan: FleetWorkerPlan) -> None:
        if not plan.worker_id or not plan.role or not plan.objective:
            raise ValueError("worker_id, role, and objective are required")
        with self._lock:
            if plan.worker_id in self._plans:
                raise ValueError(f"worker_id already registered: {plan.worker_id}")
            if len(self._plans) >= self.max_workers:
                raise ValueError("max_workers limit reached")
            self._plans[plan.worker_id] = plan

    def register_worker(self, worker_id: str, role: str, objective: str, runner: FleetWorkerCallable, **kwargs: Any) -> FleetWorkerPlan:
        plan = FleetWorkerPlan(worker_id=worker_id, role=role, objective=objective, runner=runner, **kwargs)
        self.register(plan)
        return plan

    def unregister(self, worker_id: str) -> None:
        with self._lock:
            self._plans.pop(worker_id)

    def plans(self) -> List[FleetWorkerPlan]:
        with self._lock:
            return [self._plans[key] for key in sorted(self._plans)]

    def status(self, task_id: str) -> FleetStatus:
        with self._lock:
            statuses = self._statuses.get(task_id, {})
            ordered = tuple(statuses[key] for key in sorted(statuses))
            state = self._task_status.get(task_id, "unknown")
        return FleetStatus(task_id=task_id, status=state, workers=ordered)

    def cancel(self, task_id: str) -> None:
        with self._lock:
            harness = self._tasks.get(task_id)
        if harness is not None:
            harness.cancel(task_id)
            with self._lock:
                self._task_status[task_id] = "cancelling"

    def run(
        self,
        task_id: str,
        *,
        context: Optional[Mapping[str, Any]] = None,
        worker_ids: Optional[Sequence[str]] = None,
    ) -> CollaborationResult:
        with self._lock:
            if task_id in self._tasks:
                raise ValueError(f"task_id already active: {task_id}")
            ids = list(worker_ids) if worker_ids is not None else list(self._plans)
            if not ids:
                raise ValueError("at least one worker is required")
            if len(ids) > self.max_workers:
                raise ValueError("worker count exceeds max_workers")
            unknown = sorted(set(ids) - set(self._plans))
            if unknown:
                raise KeyError(f"unknown workers: {unknown}")
            harness = CollaborationHarness(runtime=self.runtime, max_concurrent_workers=self.max_concurrent_workers)
            self._tasks[task_id] = harness
            self._task_status[task_id] = "queued"
            self._statuses[task_id] = {
                worker_id: FleetWorkerStatus(worker_id, self._plans[worker_id].role, self._plans[worker_id].objective, "queued")
                for worker_id in ids
            }
            plans = [self._plans[worker_id] for worker_id in ids]

        for plan in plans:
            def make_runner(p: FleetWorkerPlan):
                def runner(worker_context: Mapping[str, Any], execution: ExecutionRecord) -> Any:
                    self._set_status(task_id, p.worker_id, "running", execution)
                    self.runtime.events.emit(
                        "worker.progress",
                        execution_id=execution.execution_id,
                        task_id=task_id,
                        session_id=execution.session_id,
                        status="running",
                        agent_id=execution.agent_id,
                        workspace_id=execution.workspace.workspace_id,
                        metadata={"worker_id": p.worker_id, "role": p.role, "objective": p.objective},
                    )
                    return p.runner(worker_context, execution)
                return runner
            harness.register(worker_id=plan.worker_id, runner=make_runner(plan), agent_id=plan.agent_id,
                             capabilities=tuple(plan.capabilities), workspace=plan.workspace, metadata=plan.metadata)

        with self._lock:
            self._task_status[task_id] = "running"
        try:
            result = harness.run(task_id, context=context)
            with self._lock:
                for worker in result.workers:
                    plan = self._plans[worker.worker_id]
                    self._statuses[task_id][worker.worker_id] = FleetWorkerStatus(
                        worker.worker_id, plan.role, plan.objective, worker.status,
                        worker.execution_id, worker.session_id, worker.error, worker.result,
                    )
                self._task_status[task_id] = result.status
            self.runtime.events.emit(
                "fleet.completed",
                execution_id="",
                task_id=task_id,
                session_id="",
                status=result.status,
                metadata={"worker_count": len(result.workers)},
            )
            return result
        finally:
            with self._lock:
                self._tasks.pop(task_id, None)

    def _set_status(self, task_id: str, worker_id: str, status: str, execution: ExecutionRecord) -> None:
        with self._lock:
            current = self._statuses.get(task_id, {}).get(worker_id)
            if current is None:
                return
            self._statuses[task_id][worker_id] = FleetWorkerStatus(
                worker_id, current.role, current.objective, status,
                execution.execution_id, execution.session_id,
            )


__all__ = ["FleetWorkerPlan", "FleetWorkerStatus", "FleetStatus", "WorkerFleet"]
