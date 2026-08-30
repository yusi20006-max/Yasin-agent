"""
jobs.py — Persistent jobs and scheduling on top of ExecutionRuntime (Issue #33).

A Job is a durable definition of work that may produce one or more
ExecutionRuntime executions. Jobs survive process restart; the scheduler
is responsible for creating executions idempotently and never duplicating
work after recovery.

Design rules:
- Job definition is separate from execution instance.
- Scheduler integrates with ExecutionRuntime; it does not bypass it.
- Events use the existing EventEmitter infrastructure.
- Persistence is provider-agnostic (in-memory / JSON file).
- Retry is bounded; failed jobs expose diagnostics.
- Core runtime remains usable without the scheduler.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

from .execution import (
    EventEmitter,
    ExecutionEventType,
    ExecutionRuntime,
    ExecutionState,
    redact_secrets,
)
from .state_machine import InvalidTransitionError


class JobState(str, Enum):
    """Lifecycle states for a durable job."""

    QUEUED = "queued"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_JOB_TRANSITIONS: Dict[JobState, Set[JobState]] = {
    JobState.QUEUED: {
        JobState.SCHEDULED,
        JobState.RUNNING,
        JobState.CANCELLED,
        JobState.FAILED,
    },
    JobState.SCHEDULED: {
        JobState.RUNNING,
        JobState.PAUSED,
        JobState.CANCELLED,
        JobState.FAILED,
    },
    JobState.RUNNING: {
        JobState.PAUSED,
        JobState.SUCCEEDED,
        JobState.FAILED,
        JobState.CANCELLED,
        JobState.SCHEDULED,  # retry or recurrence
    },
    JobState.PAUSED: {
        JobState.RUNNING,
        JobState.SCHEDULED,
        JobState.CANCELLED,
        JobState.FAILED,
    },
    JobState.SUCCEEDED: set(),
    JobState.FAILED: set(),
    JobState.CANCELLED: set(),
}

_JOB_TERMINAL: Set[JobState] = {
    JobState.SUCCEEDED,
    JobState.FAILED,
    JobState.CANCELLED,
}


class JobEventType(str, Enum):
    CREATED = "job.created"
    SCHEDULED = "job.scheduled"
    STARTED = "job.started"
    PAUSED = "job.paused"
    RESUMED = "job.resumed"
    SUCCEEDED = "job.succeeded"
    FAILED = "job.failed"
    CANCELLED = "job.cancelled"
    RETRY = "job.retry"
    STATE_CHANGED = "job.state_changed"


@dataclass
class RetryPolicy:
    """Bounded retry policy for a job."""

    max_attempts: int = 1
    backoff_seconds: float = 0.0
    max_backoff_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.backoff_seconds < 0:
            raise ValueError("backoff_seconds must be >= 0")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "max_attempts": self.max_attempts,
            "backoff_seconds": self.backoff_seconds,
            "max_backoff_seconds": self.max_backoff_seconds,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "RetryPolicy":
        if not data:
            return cls()
        return cls(
            max_attempts=int(data.get("max_attempts", 1)),
            backoff_seconds=float(data.get("backoff_seconds", 0.0)),
            max_backoff_seconds=float(data.get("max_backoff_seconds", 300.0)),
        )

    def next_backoff(self, attempt: int) -> float:
        """Exponential backoff capped at max_backoff_seconds."""
        if attempt <= 1:
            return 0.0
        delay = self.backoff_seconds * (2 ** (attempt - 2))
        return min(delay, self.max_backoff_seconds)


@dataclass
class ScheduleSpec:
    """
    When a job should run.

    - run_at: absolute unix timestamp for one-shot delayed/scheduled run
    - interval_seconds: if set, recurring every N seconds after completion
    - immediate: if True and no run_at, run as soon as possible
    """

    run_at: Optional[float] = None
    interval_seconds: Optional[float] = None
    immediate: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "run_at": self.run_at,
            "interval_seconds": self.interval_seconds,
            "immediate": self.immediate,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ScheduleSpec":
        if not data:
            return cls()
        return cls(
            run_at=data.get("run_at"),
            interval_seconds=data.get("interval_seconds"),
            immediate=bool(data.get("immediate", True)),
        )

    def is_due(self, now: Optional[float] = None) -> bool:
        now = now if now is not None else time.time()
        if self.run_at is not None:
            return now >= self.run_at
        return self.immediate


@dataclass
class JobRecord:
    """Durable job definition + runtime state."""

    job_id: str
    task_id: str
    status: JobState = JobState.QUEUED
    schedule: ScheduleSpec = field(default_factory=ScheduleSpec)
    execution_id: Optional[str] = None
    session_id: Optional[str] = None
    agent_id: Optional[str] = None
    capabilities: frozenset = field(default_factory=frozenset)
    metadata: Dict[str, Any] = field(default_factory=dict)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    attempt: int = 0
    last_error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    next_run_at: Optional[float] = None
    checkpoint: Optional[Dict[str, Any]] = None
    history: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.history:
            self.history = [self.status.value]
        if isinstance(self.capabilities, (list, set, tuple)):
            self.capabilities = frozenset(self.capabilities)
        if isinstance(self.schedule, dict):
            self.schedule = ScheduleSpec.from_dict(self.schedule)
        if isinstance(self.retry, dict):
            self.retry = RetryPolicy.from_dict(self.retry)
        if isinstance(self.status, str):
            self.status = JobState(self.status)

    def is_terminal(self) -> bool:
        return self.status in _JOB_TERMINAL

    def can_transition(self, target: JobState) -> bool:
        return target in _JOB_TRANSITIONS.get(self.status, set())

    def transition(self, target: JobState) -> JobState:
        if not self.can_transition(target):
            raise InvalidTransitionError(
                f"invalid job transition {self.status.value} -> {target.value}"
            )
        self.status = target
        self.updated_at = time.time()
        self.history.append(target.value)
        if target == JobState.RUNNING and self.started_at is None:
            self.started_at = time.time()
        if target in _JOB_TERMINAL:
            self.finished_at = time.time()
        return self.status

    def as_dict(self) -> Dict[str, Any]:
        return redact_secrets(
            {
                "job_id": self.job_id,
                "task_id": self.task_id,
                "status": self.status.value,
                "schedule": self.schedule.as_dict(),
                "execution_id": self.execution_id,
                "session_id": self.session_id,
                "agent_id": self.agent_id,
                "capabilities": sorted(self.capabilities),
                "metadata": dict(self.metadata),
                "retry": self.retry.as_dict(),
                "attempt": self.attempt,
                "last_error": self.last_error,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "next_run_at": self.next_run_at,
                "checkpoint": self.checkpoint,
                "history": list(self.history),
            }
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JobRecord":
        return cls(
            job_id=str(data["job_id"]),
            task_id=str(data["task_id"]),
            status=JobState(data.get("status", JobState.QUEUED.value)),
            schedule=ScheduleSpec.from_dict(data.get("schedule")),
            execution_id=data.get("execution_id"),
            session_id=data.get("session_id"),
            agent_id=data.get("agent_id"),
            capabilities=frozenset(data.get("capabilities") or ()),
            metadata=dict(data.get("metadata") or {}),
            retry=RetryPolicy.from_dict(data.get("retry")),
            attempt=int(data.get("attempt") or 0),
            last_error=data.get("last_error"),
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            next_run_at=data.get("next_run_at"),
            checkpoint=data.get("checkpoint"),
            history=list(data.get("history") or []),
        )


class JobStore:
    """Abstract persistence for jobs."""

    def save(self, job_id: str, payload: Dict[str, Any]) -> None:
        raise NotImplementedError

    def load(self, job_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def delete(self, job_id: str) -> None:
        raise NotImplementedError

    def list_ids(self) -> List[str]:
        raise NotImplementedError


class InMemoryJobStore(JobStore):
    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def save(self, job_id: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._data[job_id] = dict(payload)

    def load(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            item = self._data.get(job_id)
            return dict(item) if item is not None else None

    def delete(self, job_id: str) -> None:
        with self._lock:
            self._data.pop(job_id, None)

    def list_ids(self) -> List[str]:
        with self._lock:
            return list(self._data.keys())

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class JsonFileJobStore(JobStore):
    """One JSON file per job_id under a root directory."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, job_id: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in job_id)
        if not safe:
            safe = "unknown"
        return self.root / f"{safe}.json"

    def save(self, job_id: str, payload: Dict[str, Any]) -> None:
        path = self._path(job_id)
        tmp = path.with_suffix(".json.tmp")
        data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        with self._lock:
            tmp.write_text(data, encoding="utf-8")
            os.replace(tmp, path)

    def load(self, job_id: str) -> Optional[Dict[str, Any]]:
        path = self._path(job_id)
        with self._lock:
            if not path.is_file():
                return None
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None

    def delete(self, job_id: str) -> None:
        path = self._path(job_id)
        with self._lock:
            if path.is_file():
                path.unlink()

    def list_ids(self) -> List[str]:
        with self._lock:
            ids: List[str] = []
            for path in self.root.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    jid = data.get("job_id")
                    if jid:
                        ids.append(str(jid))
                except (json.JSONDecodeError, OSError):
                    continue
            return ids


class JobScheduler:
    """
    Durable job scheduler integrated with ExecutionRuntime.

    - create_job: durable definition
    - schedule / tick: move due jobs to running by creating executions
    - pause / resume / cancel: job-level controls
    - on_execution_terminal: map execution outcome back to job + retries
    - recover / recover_all: load from store after process restart
    """

    def __init__(
        self,
        runtime: ExecutionRuntime,
        store: Optional[JobStore] = None,
        emitter: Optional[EventEmitter] = None,
        *,
        max_concurrent: Optional[int] = None,
    ) -> None:
        if max_concurrent is not None and max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self._runtime = runtime
        self._store: Optional[JobStore] = store
        self._emitter = emitter or runtime.events
        self._jobs: Dict[str, JobRecord] = {}
        self._lock = threading.RLock()
        # Track which execution_ids were created by this scheduler to avoid
        # double-processing after recovery.
        self._known_executions: Set[str] = set()
        # Bounded concurrency: None means unlimited.
        self._max_concurrent = max_concurrent

    @property
    def runtime(self) -> ExecutionRuntime:
        return self._runtime

    @property
    def max_concurrent(self) -> Optional[int]:
        return self._max_concurrent

    def _running_count(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if j.status == JobState.RUNNING)

    def enqueue(
        self,
        *,
        task_id: str,
        schedule: Optional[ScheduleSpec] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        capabilities: Optional[Sequence[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        retry: Optional[RetryPolicy] = None,
        job_id: Optional[str] = None,
        run_immediately: bool = False,
    ) -> JobRecord:
        """Alias for create_job — enqueue a durable job definition."""
        return self.create_job(
            task_id=task_id,
            schedule=schedule,
            session_id=session_id,
            agent_id=agent_id,
            capabilities=capabilities,
            metadata=metadata,
            retry=retry,
            job_id=job_id,
            run_immediately=run_immediately,
        )

    def create_job(
        self,
        *,
        task_id: str,
        schedule: Optional[ScheduleSpec] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        capabilities: Optional[Sequence[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        retry: Optional[RetryPolicy] = None,
        job_id: Optional[str] = None,
        run_immediately: bool = False,
    ) -> JobRecord:
        """Create a durable job definition. Does not start an execution yet."""
        schedule = schedule or ScheduleSpec(immediate=True)
        job = JobRecord(
            job_id=job_id or f"job-{uuid.uuid4().hex[:16]}",
            task_id=task_id,
            status=JobState.QUEUED,
            schedule=schedule,
            session_id=session_id,
            agent_id=agent_id,
            capabilities=frozenset(capabilities or ()),
            metadata=dict(metadata or {}),
            retry=retry or RetryPolicy(),
            next_run_at=schedule.run_at,
        )
        if schedule.run_at is not None:
            job.status = JobState.SCHEDULED
            job.history = [JobState.QUEUED.value, JobState.SCHEDULED.value]
        with self._lock:
            if job.job_id in self._jobs:
                raise ValueError(f"job_id already exists: {job.job_id}")
            self._jobs[job.job_id] = job
        self._emit(JobEventType.CREATED.value, job)
        if job.status == JobState.SCHEDULED:
            self._emit(JobEventType.SCHEDULED.value, job)
        self._persist(job)
        if run_immediately or (
            schedule.immediate and schedule.run_at is None
        ):
            return self.tick(job_id=job.job_id, force=True) or job
        return job

    def get(self, job_id: str) -> Optional[JobRecord]:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(
        self,
        *,
        task_id: Optional[str] = None,
        status: Optional[JobState] = None,
    ) -> List[JobRecord]:
        with self._lock:
            items = list(self._jobs.values())
        if task_id is not None:
            items = [j for j in items if j.task_id == task_id]
        if status is not None:
            items = [j for j in items if j.status == status]
        return items

    def tick(
        self,
        *,
        job_id: Optional[str] = None,
        now: Optional[float] = None,
        force: bool = False,
    ) -> Optional[JobRecord]:
        """
        Advance the scheduler.

        If job_id is given, only that job is considered.
        Otherwise all due non-terminal jobs are considered, subject to
        ``max_concurrent`` (when set).

        Returns the last job that was started (or None if nothing due /
        concurrency saturated).
        """
        now = now if now is not None else time.time()
        candidates: List[JobRecord]
        with self._lock:
            if job_id is not None:
                job = self._jobs.get(job_id)
                if job is None:
                    raise KeyError(f"unknown job_id: {job_id}")
                candidates = [job]
            else:
                candidates = [
                    j
                    for j in self._jobs.values()
                    if not j.is_terminal()
                    and j.status
                    in (JobState.QUEUED, JobState.SCHEDULED, JobState.PAUSED)
                ]
                # Deterministic order for tests: oldest first.
                candidates.sort(key=lambda j: (j.created_at, j.job_id))

        started: Optional[JobRecord] = None
        for job in candidates:
            if job.status == JobState.PAUSED and not force:
                continue
            due = force or job.schedule.is_due(now)
            if job.next_run_at is not None and not force:
                due = now >= job.next_run_at
            if not due:
                continue
            # Idempotency: if an execution is already attached and still
            # non-terminal, do not create another.
            if job.execution_id and job.execution_id in self._known_executions:
                rec = self._runtime.get(job.execution_id)
                if rec is not None and not rec.is_terminal():
                    continue
            # Bounded concurrency
            if self._max_concurrent is not None:
                if self._running_count() >= self._max_concurrent:
                    break
            started = self._start_execution(job)
        return started

    def _start_execution(self, job: JobRecord) -> JobRecord:
        """Create + start an execution for this job via ExecutionRuntime."""
        with self._lock:
            if job.is_terminal():
                return job
            # Guard against concurrent double-start after restart.
            if (
                job.execution_id
                and job.execution_id in self._known_executions
            ):
                rec = self._runtime.get(job.execution_id)
                if rec is not None and not rec.is_terminal():
                    return job

            job.attempt += 1
            meta = dict(job.metadata)
            meta["job_id"] = job.job_id
            meta["job_attempt"] = job.attempt
            rec = self._runtime.create(
                task_id=job.task_id,
                session_id=job.session_id,
                agent_id=job.agent_id,
                capabilities=list(job.capabilities),
                metadata=meta,
            )
            job.execution_id = rec.execution_id
            self._known_executions.add(rec.execution_id)
            if job.status in (JobState.QUEUED, JobState.SCHEDULED, JobState.PAUSED):
                job.transition(JobState.RUNNING)
            else:
                job.status = JobState.RUNNING
                job.updated_at = time.time()
                if JobState.RUNNING.value not in job.history:
                    job.history.append(JobState.RUNNING.value)
            job.last_error = None
            job.next_run_at = None
        self._runtime.start(rec.execution_id)
        self._emit(JobEventType.STARTED.value, job, extra={"execution_id": rec.execution_id})
        self._emit(JobEventType.STATE_CHANGED.value, job)
        self._persist(job)
        return job

    def on_execution_terminal(
        self,
        execution_id: str,
        *,
        success: bool,
        error: Optional[str] = None,
    ) -> Optional[JobRecord]:
        """
        Called when an execution reaches a terminal state.
        Maps outcome onto the owning job and applies retry / recurrence.
        """
        with self._lock:
            job = None
            for j in self._jobs.values():
                if j.execution_id == execution_id:
                    job = j
                    break
            if job is None or job.is_terminal():
                return job

            if success:
                # Recurring?
                if (
                    job.schedule.interval_seconds is not None
                    and job.schedule.interval_seconds > 0
                ):
                    job.transition(JobState.SCHEDULED)
                    job.next_run_at = time.time() + job.schedule.interval_seconds
                    job.execution_id = None  # next tick creates a new one
                    job.last_error = None
                    self._emit(JobEventType.SCHEDULED.value, job)
                    self._emit(JobEventType.STATE_CHANGED.value, job)
                    self._persist(job)
                    return job
                job.transition(JobState.SUCCEEDED)
                self._emit(JobEventType.SUCCEEDED.value, job)
                self._emit(JobEventType.STATE_CHANGED.value, job)
                self._persist(job)
                return job

            # Failure path
            job.last_error = error or "execution failed"
            if job.attempt < job.retry.max_attempts:
                delay = job.retry.next_backoff(job.attempt + 1)
                job.transition(JobState.SCHEDULED)
                job.next_run_at = time.time() + delay
                job.execution_id = None
                self._emit(
                    JobEventType.RETRY.value,
                    job,
                    extra={
                        "attempt": job.attempt,
                        "next_run_at": job.next_run_at,
                        "error": job.last_error,
                    },
                )
                self._emit(JobEventType.STATE_CHANGED.value, job)
                self._persist(job)
                return job

            job.transition(JobState.FAILED)
            self._emit(
                JobEventType.FAILED.value,
                job,
                extra={"error": job.last_error, "attempt": job.attempt},
            )
            self._emit(JobEventType.STATE_CHANGED.value, job)
            self._persist(job)
            return job

    def pause(self, job_id: str) -> JobRecord:
        job = self._require(job_id)
        if job.is_terminal():
            raise InvalidTransitionError(
                f"cannot pause terminal job: {job.status.value}"
            )
        if job.status == JobState.PAUSED:
            return job
        job.transition(JobState.PAUSED)
        if job.execution_id:
            try:
                rec = self._runtime.get(job.execution_id)
                if rec is not None and not rec.is_terminal():
                    self._runtime.pause(job.execution_id)
            except (KeyError, InvalidTransitionError):
                pass
        self._emit(JobEventType.PAUSED.value, job)
        self._emit(JobEventType.STATE_CHANGED.value, job)
        self._persist(job)
        return job

    def resume(self, job_id: str) -> JobRecord:
        try:
            job = self._require(job_id)
        except KeyError:
            job = self.recover(job_id)
        if job.is_terminal():
            raise InvalidTransitionError(
                f"cannot resume terminal job: {job.status.value}"
            )
        if job.status == JobState.RUNNING:
            return job
        if job.status == JobState.PAUSED:
            # Prefer resuming existing execution if still non-terminal.
            if job.execution_id:
                rec = self._runtime.get(job.execution_id)
                if rec is None:
                    try:
                        rec = self._runtime.recover(job.execution_id)
                    except (KeyError, ValueError):
                        rec = None
                if rec is not None and not rec.is_terminal():
                    self._runtime.resume(job.execution_id)
                    job.transition(JobState.RUNNING)
                    self._emit(JobEventType.RESUMED.value, job)
                    self._emit(JobEventType.STATE_CHANGED.value, job)
                    self._persist(job)
                    return job
            # Otherwise re-schedule for immediate tick.
            job.transition(JobState.SCHEDULED)
            job.next_run_at = time.time()
            self._emit(JobEventType.RESUMED.value, job)
            self._emit(JobEventType.STATE_CHANGED.value, job)
            self._persist(job)
            return self.tick(job_id=job.job_id, force=True) or job
        if job.status in (JobState.QUEUED, JobState.SCHEDULED):
            return self.tick(job_id=job.job_id, force=True) or job
        return job

    def cancel(self, job_id: str) -> JobRecord:
        job = self._require(job_id)
        if job.is_terminal():
            if job.status == JobState.CANCELLED:
                return job
            raise InvalidTransitionError(
                f"cannot cancel terminal job: {job.status.value}"
            )
        job.transition(JobState.CANCELLED)
        if job.execution_id:
            try:
                rec = self._runtime.get(job.execution_id)
                if rec is not None and not rec.is_terminal():
                    self._runtime.cancel(job.execution_id)
            except (KeyError, InvalidTransitionError):
                pass
        self._emit(JobEventType.CANCELLED.value, job)
        self._emit(JobEventType.STATE_CHANGED.value, job)
        self._persist(job)
        return job

    def save_checkpoint(
        self, job_id: str, data: Dict[str, Any], *, merge: bool = True
    ) -> JobRecord:
        job = self._require(job_id)
        if job.is_terminal():
            raise InvalidTransitionError(
                "cannot checkpoint terminal job"
            )
        safe = redact_secrets(data)
        if not isinstance(safe, dict):
            safe = {}
        if merge and job.checkpoint:
            merged = dict(job.checkpoint)
            merged.update(safe)
            job.checkpoint = merged
        else:
            job.checkpoint = safe
        job.updated_at = time.time()
        self._persist(job)
        return job

    def recover(self, job_id: str) -> JobRecord:
        with self._lock:
            if job_id in self._jobs:
                return self._jobs[job_id]
        if self._store is None:
            raise KeyError(f"unknown job_id: {job_id}")
        payload = self._store.load(job_id)
        if payload is None:
            raise KeyError(f"unknown job_id: {job_id}")
        try:
            job = JobRecord.from_dict(payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"corrupted job snapshot: {job_id}") from exc
        with self._lock:
            if job_id in self._jobs:
                return self._jobs[job_id]
            self._jobs[job_id] = job
            if job.execution_id:
                self._known_executions.add(job.execution_id)
        # Also recover the linked execution if needed.
        if job.execution_id:
            try:
                if self._runtime.get(job.execution_id) is None:
                    self._runtime.recover(job.execution_id)
            except (KeyError, ValueError):
                pass
        self._emit(
            JobEventType.STATE_CHANGED.value,
            job,
            extra={"recovered": True},
        )
        return job

    def recover_all(self) -> List[JobRecord]:
        if self._store is None:
            return []
        recovered: List[JobRecord] = []
        for jid in self._store.list_ids():
            try:
                recovered.append(self.recover(jid))
            except (KeyError, ValueError):
                continue
        return recovered

    def list_recoverable(self) -> List[JobRecord]:
        with self._lock:
            items = list(self._jobs.values())
        return [j for j in items if not j.is_terminal()]

    def _require(self, job_id: str) -> JobRecord:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"unknown job_id: {job_id}")
        return job

    def _persist(self, job: JobRecord) -> None:
        if self._store is None:
            return
        try:
            self._store.save(job.job_id, job.as_dict())
        except Exception:
            # Persistence failure must not break in-process authority.
            pass

    def _emit(
        self,
        event_type: str,
        job: JobRecord,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        metadata: Dict[str, Any] = {
            "status": job.status.value,
            "job_id": job.job_id,
            "attempt": job.attempt,
        }
        if job.execution_id:
            metadata["execution_id"] = job.execution_id
        if extra:
            metadata.update(extra)
        self._emitter.emit(
            event_type,
            execution_id=job.execution_id or job.job_id,
            task_id=job.task_id,
            session_id=job.session_id or "",
            status=job.status.value,
            metadata=metadata,
            agent_id=job.agent_id,
        )


__all__ = [
    "JobState",
    "JobEventType",
    "RetryPolicy",
    "ScheduleSpec",
    "JobRecord",
    "JobStore",
    "InMemoryJobStore",
    "JsonFileJobStore",
    "JobScheduler",
]
