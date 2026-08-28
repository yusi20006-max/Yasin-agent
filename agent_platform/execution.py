"""
execution.py  Observable execution workspace boundary (Issue #26).

Yasin-Agent owns execution lifecycle, workspace metadata, capability
declaration, and structured events. Yasin-MCP remains the tool
governance and authorization boundary. YasinHub is the future
observation consumer.

This module does not provide shell execution, unrestricted filesystem
access, or privilege-escalating computer-use APIs.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence, Set

from .state_machine import InvalidTransitionError


class ExecutionState(str, Enum):
    """Observable lifecycle states for one agent execution."""

    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TRANSITIONS: Dict[ExecutionState, Set[ExecutionState]] = {
    ExecutionState.QUEUED: {ExecutionState.RUNNING, ExecutionState.CANCELLED},
    ExecutionState.RUNNING: {
        ExecutionState.PAUSED,
        ExecutionState.SUCCEEDED,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    },
    ExecutionState.PAUSED: {
        ExecutionState.RUNNING,
        ExecutionState.CANCELLED,
        ExecutionState.FAILED,
    },
    ExecutionState.SUCCEEDED: set(),
    ExecutionState.FAILED: set(),
    ExecutionState.CANCELLED: set(),
}

_TERMINAL: Set[ExecutionState] = {
    ExecutionState.SUCCEEDED,
    ExecutionState.FAILED,
    ExecutionState.CANCELLED,
}

_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|token|secret|password|credential|authorization|bearer|"
    r"private[_-]?key)",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._\-+=/]{8,}|sk-[a-z0-9]{16,}|ghp_[a-z0-9]{20,})"
)


def redact_secrets(value: Any, *, _depth: int = 0) -> Any:
    """Recursively redact secret-looking keys and common secret patterns."""
    if _depth > 8:
        return "<max-depth>"
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if _SECRET_KEY_RE.search(key_str):
                out[key_str] = "***"
            else:
                out[key_str] = redact_secrets(item, _depth=_depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [redact_secrets(item, _depth=_depth + 1) for item in value]
    if isinstance(value, str):
        return _SECRET_VALUE_RE.sub("***", value)
    return value


class ExecutionEventType(str, Enum):
    CREATED = "execution.created"
    STARTED = "execution.started"
    PAUSED = "execution.paused"
    RESUMED = "execution.resumed"
    COMPLETED = "execution.completed"
    FAILED = "execution.failed"
    CANCELLED = "execution.cancelled"
    CAPABILITY_DENIED = "capability.denied"
    STATE_CHANGED = "execution.state_changed"


@dataclass(frozen=True)
class ExecutionEvent:
    """Structured, secret-free observability event for Hub consumption."""

    event_id: str
    event_type: str
    timestamp: float
    execution_id: str
    task_id: str
    session_id: str
    status: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    agent_id: Optional[str] = None
    workspace_id: Optional[str] = None
    sequence: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "status": self.status,
            "metadata": dict(self.metadata),
            "agent_id": self.agent_id,
            "workspace_id": self.workspace_id,
            "sequence": self.sequence,
        }


EventListener = Callable[[ExecutionEvent], None]


class EventEmitter:
    """In-process event bus. Listeners must not break execution."""

    def __init__(self) -> None:
        self._listeners: List[EventListener] = []
        self._history: List[ExecutionEvent] = []
        self._lock = threading.Lock()
        self._seq = 0

    def subscribe(self, listener: EventListener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def emit(
        self,
        event_type: str,
        *,
        execution_id: str,
        task_id: str,
        session_id: str,
        status: str,
        metadata: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> ExecutionEvent:
        safe_meta = redact_secrets(metadata or {})
        if not isinstance(safe_meta, dict):
            safe_meta = {}
        with self._lock:
            self._seq += 1
            event = ExecutionEvent(
                event_id=f"evt-{uuid.uuid4().hex[:16]}",
                event_type=event_type,
                timestamp=time.time(),
                execution_id=execution_id,
                task_id=task_id,
                session_id=session_id,
                status=status,
                metadata=safe_meta,
                agent_id=agent_id,
                workspace_id=workspace_id,
                sequence=self._seq,
            )
            self._history.append(event)
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(event)
            except Exception:  # noqa: BLE001
                pass
        return event

    def history(
        self,
        *,
        execution_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> List[ExecutionEvent]:
        with self._lock:
            events = list(self._history)
        if execution_id is not None:
            events = [e for e in events if e.execution_id == execution_id]
        if task_id is not None:
            events = [e for e in events if e.task_id == task_id]
        return events

    def clear(self) -> None:
        with self._lock:
            self._history.clear()
            self._seq = 0


@dataclass(frozen=True)
class WorkspaceBound:
    """
    Explicit, inspectable workspace identity and scope.

    Presence of a workspace does NOT grant filesystem or shell access.
    """

    workspace_id: str
    path: Optional[str] = None
    scope: str = "default"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "path": self.path,
            "scope": self.scope,
            "metadata": redact_secrets(dict(self.metadata)),
        }


def make_workspace(
    workspace_id: Optional[str] = None,
    *,
    path: Optional[str] = None,
    scope: str = "default",
    metadata: Optional[Dict[str, Any]] = None,
) -> WorkspaceBound:
    return WorkspaceBound(
        workspace_id=workspace_id or f"ws-{uuid.uuid4().hex[:12]}",
        path=path,
        scope=scope,
        metadata=dict(metadata or {}),
    )


class CapabilityDeniedError(Exception):
    """Raised when a requested capability is not on the execution allow-list."""

    def __init__(self, capability: str, execution_id: str) -> None:
        self.capability = capability
        self.execution_id = execution_id
        super().__init__(
            f"capability {capability!r} denied for execution {execution_id!r}"
        )


@dataclass
class ExecutionRecord:
    """One observable agent execution."""

    task_id: str
    execution_id: str = field(default_factory=lambda: f"exec-{uuid.uuid4().hex[:16]}")
    session_id: str = field(default_factory=lambda: f"sess-{uuid.uuid4().hex[:12]}")
    agent_id: Optional[str] = None
    workspace: WorkspaceBound = field(default_factory=lambda: make_workspace())
    capabilities: frozenset = field(default_factory=frozenset)
    status: ExecutionState = ExecutionState.QUEUED
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[str] = None
    result: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    _history: List[ExecutionState] = field(
        default_factory=lambda: [ExecutionState.QUEUED]
    )
    _cancel_requested: bool = field(default=False, repr=False)

    def is_terminal(self) -> bool:
        return self.status in _TERMINAL

    def can_transition(self, target: ExecutionState) -> bool:
        return target in _TRANSITIONS.get(self.status, set())

    def transition(self, target: ExecutionState) -> ExecutionState:
        if not self.can_transition(target):
            raise InvalidTransitionError(
                f"invalid execution transition: "
                f"{self.status.value} -> {target.value}"
            )
        self.status = target
        self._history.append(target)
        if target == ExecutionState.RUNNING and self.started_at is None:
            self.started_at = time.time()
        if target in _TERMINAL:
            self.finished_at = time.time()
        return self.status

    @property
    def history(self) -> List[ExecutionState]:
        return list(self._history)

    def request_cancel(self) -> None:
        self._cancel_requested = True

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested

    def allows_capability(self, capability: str) -> bool:
        if not self.capabilities:
            return False
        return capability in self.capabilities

    def as_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "workspace": self.workspace.as_dict(),
            "capabilities": sorted(self.capabilities),
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "result": redact_secrets(self.result),
            "metadata": redact_secrets(dict(self.metadata)),
            "history": [s.value for s in self._history],
        }


class ExecutionRuntime:
    """
    Authoritative boundary for creating and controlling executions.

    Pause is cooperative: state moves to paused and events are emitted;
    in-flight tool calls are not preempted. True preemptive pause would
    require an async runtime and is intentionally out of scope.
    """

    def __init__(self, emitter: Optional[EventEmitter] = None) -> None:
        self._emitter = emitter or EventEmitter()
        self._executions: Dict[str, ExecutionRecord] = {}
        self._lock = threading.RLock()

    @property
    def events(self) -> EventEmitter:
        return self._emitter

    def create(
        self,
        *,
        task_id: str,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        workspace: Optional[WorkspaceBound] = None,
        capabilities: Optional[Sequence[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        execution_id: Optional[str] = None,
    ) -> ExecutionRecord:
        record = ExecutionRecord(
            task_id=task_id,
            execution_id=execution_id or f"exec-{uuid.uuid4().hex[:16]}",
            session_id=session_id or f"sess-{uuid.uuid4().hex[:12]}",
            agent_id=agent_id,
            workspace=workspace or make_workspace(),
            capabilities=frozenset(capabilities or ()),
            metadata=dict(metadata or {}),
        )
        with self._lock:
            if record.execution_id in self._executions:
                raise ValueError(
                    f"execution_id already exists: {record.execution_id}"
                )
            self._executions[record.execution_id] = record
        self._emit(ExecutionEventType.CREATED.value, record)
        return record

    def get(self, execution_id: str) -> Optional[ExecutionRecord]:
        with self._lock:
            return self._executions.get(execution_id)

    def list_executions(
        self,
        *,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> List[ExecutionRecord]:
        with self._lock:
            items = list(self._executions.values())
        if task_id is not None:
            items = [e for e in items if e.task_id == task_id]
        if session_id is not None:
            items = [e for e in items if e.session_id == session_id]
        return items

    def start(self, execution_id: str) -> ExecutionRecord:
        record = self._require(execution_id)
        record.transition(ExecutionState.RUNNING)
        self._emit(ExecutionEventType.STARTED.value, record)
        self._emit(ExecutionEventType.STATE_CHANGED.value, record)
        return record

    def pause(self, execution_id: str) -> ExecutionRecord:
        """Cooperative pause  does not preempt an in-flight operation."""
        record = self._require(execution_id)
        record.transition(ExecutionState.PAUSED)
        self._emit(
            ExecutionEventType.PAUSED.value,
            record,
            extra={"cooperative": True},
        )
        self._emit(ExecutionEventType.STATE_CHANGED.value, record)
        return record

    def resume(self, execution_id: str) -> ExecutionRecord:
        record = self._require(execution_id)
        record.transition(ExecutionState.RUNNING)
        self._emit(ExecutionEventType.RESUMED.value, record)
        self._emit(ExecutionEventType.STATE_CHANGED.value, record)
        return record

    def complete(self, execution_id: str, result: Any = None) -> ExecutionRecord:
        record = self._require(execution_id)
        if record.cancel_requested and not record.is_terminal():
            return self.cancel(execution_id)
        record.result = result
        record.transition(ExecutionState.SUCCEEDED)
        self._emit(
            ExecutionEventType.COMPLETED.value,
            record,
            extra={"success": True},
        )
        self._emit(ExecutionEventType.STATE_CHANGED.value, record)
        return record

    def fail(self, execution_id: str, error: str) -> ExecutionRecord:
        record = self._require(execution_id)
        safe_error = redact_secrets(error)
        if not isinstance(safe_error, str):
            safe_error = str(safe_error)
        record.error = safe_error
        if not record.is_terminal():
            record.transition(ExecutionState.FAILED)
        self._emit(
            ExecutionEventType.FAILED.value,
            record,
            extra={"error": safe_error},
        )
        self._emit(ExecutionEventType.STATE_CHANGED.value, record)
        return record

    def cancel(self, execution_id: str) -> ExecutionRecord:
        record = self._require(execution_id)
        record.request_cancel()
        if record.is_terminal():
            return record
        record.transition(ExecutionState.CANCELLED)
        self._emit(ExecutionEventType.CANCELLED.value, record)
        self._emit(ExecutionEventType.STATE_CHANGED.value, record)
        return record

    def check_capability(self, execution_id: str, capability: str) -> None:
        record = self._require(execution_id)
        if record.allows_capability(capability):
            return
        self._emit(
            ExecutionEventType.CAPABILITY_DENIED.value,
            record,
            extra={"capability": capability},
        )
        raise CapabilityDeniedError(capability, record.execution_id)

    def _require(self, execution_id: str) -> ExecutionRecord:
        with self._lock:
            record = self._executions.get(execution_id)
        if record is None:
            raise KeyError(f"unknown execution_id: {execution_id}")
        return record

    def _emit(
        self,
        event_type: str,
        record: ExecutionRecord,
        extra: Optional[Dict[str, Any]] = None,
    ) -> ExecutionEvent:
        metadata: Dict[str, Any] = {"status": record.status.value}
        if extra:
            metadata.update(extra)
        return self._emitter.emit(
            event_type,
            execution_id=record.execution_id,
            task_id=record.task_id,
            session_id=record.session_id,
            status=record.status.value,
            metadata=metadata,
            agent_id=record.agent_id,
            workspace_id=record.workspace.workspace_id,
        )


__all__ = [
    "ExecutionState",
    "ExecutionEventType",
    "ExecutionEvent",
    "EventEmitter",
    "WorkspaceBound",
    "make_workspace",
    "CapabilityDeniedError",
    "ExecutionRecord",
    "ExecutionRuntime",
    "redact_secrets",
]
