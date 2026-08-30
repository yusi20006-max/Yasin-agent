"""
observability.py — Production observability + execution diagnostics (Issue #42).

Dependency-light: structured counters/gauges, correlation helpers, health
payloads, and execution diagnostics. Secrets never logged.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .execution import ExecutionRecord, ExecutionState, redact_secrets

logger = logging.getLogger("yasin.agent")


class ErrorClass(str, Enum):
    AUTH = "auth"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    VALIDATION = "validation"
    TIMEOUT = "timeout"
    PROVIDER = "provider"
    INTERNAL = "internal"
    CANCELLED = "cancelled"
    CAPABILITY = "capability"


@dataclass
class RuntimeMetrics:
    """In-process counters and gauges for operational visibility."""

    executions_created: int = 0
    executions_running: int = 0
    executions_succeeded: int = 0
    executions_failed: int = 0
    executions_cancelled: int = 0
    executions_paused: int = 0
    scheduler_failures: int = 0
    http_errors: int = 0
    http_requests: int = 0
    ai_capability_failures: int = 0
    research_failures: int = 0
    total_execution_duration_seconds: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def inc(self, name: str, value: int = 1) -> None:
        with self._lock:
            cur = getattr(self, name, None)
            if isinstance(cur, (int, float)):
                setattr(self, name, type(cur)(cur + value))

    def add_duration(self, seconds: float) -> None:
        with self._lock:
            self.total_execution_duration_seconds += max(0.0, seconds)

    def on_execution_status(self, status: str) -> None:
        """Adjust gauges/counters from a lifecycle status string."""
        with self._lock:
            if status == ExecutionState.RUNNING.value:
                self.executions_running += 1
            elif status == ExecutionState.SUCCEEDED.value:
                self.executions_succeeded += 1
                if self.executions_running > 0:
                    self.executions_running -= 1
            elif status == ExecutionState.FAILED.value:
                self.executions_failed += 1
                if self.executions_running > 0:
                    self.executions_running -= 1
            elif status == ExecutionState.CANCELLED.value:
                self.executions_cancelled += 1
                if self.executions_running > 0:
                    self.executions_running -= 1
            elif status == ExecutionState.PAUSED.value:
                self.executions_paused += 1
                if self.executions_running > 0:
                    self.executions_running -= 1

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "executions_created": self.executions_created,
                "executions_running": self.executions_running,
                "executions_succeeded": self.executions_succeeded,
                "executions_failed": self.executions_failed,
                "executions_cancelled": self.executions_cancelled,
                "executions_paused": self.executions_paused,
                "scheduler_failures": self.scheduler_failures,
                "http_errors": self.http_errors,
                "http_requests": self.http_requests,
                "ai_capability_failures": self.ai_capability_failures,
                "research_failures": self.research_failures,
                "total_execution_duration_seconds": round(
                    self.total_execution_duration_seconds, 3
                ),
            }

    def reset(self) -> None:
        with self._lock:
            self.executions_created = 0
            self.executions_running = 0
            self.executions_succeeded = 0
            self.executions_failed = 0
            self.executions_cancelled = 0
            self.executions_paused = 0
            self.scheduler_failures = 0
            self.http_errors = 0
            self.http_requests = 0
            self.ai_capability_failures = 0
            self.research_failures = 0
            self.total_execution_duration_seconds = 0.0


_GLOBAL_METRICS = RuntimeMetrics()


def get_metrics() -> RuntimeMetrics:
    return _GLOBAL_METRICS


def correlation_context(
    *,
    request_id: Optional[str] = None,
    execution_id: Optional[str] = None,
    job_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Dict[str, str]:
    """Build a secret-free correlation dict for structured logs/events."""
    ctx = {
        "request_id": request_id,
        "execution_id": execution_id,
        "job_id": job_id,
        "task_id": task_id,
        "session_id": session_id,
        "agent_id": agent_id,
    }
    return {k: v for k, v in ctx.items() if v}


def safe_log_extra(data: Dict[str, Any]) -> Dict[str, Any]:
    """Redact secrets from a log payload."""
    redacted = redact_secrets(data)
    return redacted if isinstance(redacted, dict) else {}


def classify_error(
    *,
    status_code: Optional[int] = None,
    error_code: Optional[str] = None,
    message: Optional[str] = None,
) -> str:
    if status_code == 401:
        return ErrorClass.AUTH.value
    if status_code == 404:
        return ErrorClass.NOT_FOUND.value
    if status_code == 409:
        return ErrorClass.CONFLICT.value
    if status_code == 400:
        return ErrorClass.VALIDATION.value
    if error_code:
        ec = error_code.lower()
        if "timeout" in ec:
            return ErrorClass.TIMEOUT.value
        if "unauthor" in ec or "denied" in ec or "capability" in ec:
            return ErrorClass.CAPABILITY.value
        if "provider" in ec:
            return ErrorClass.PROVIDER.value
        if "cancel" in ec:
            return ErrorClass.CANCELLED.value
    if message and "timeout" in message.lower():
        return ErrorClass.TIMEOUT.value
    return ErrorClass.INTERNAL.value


def execution_diagnostics(record: ExecutionRecord) -> Dict[str, Any]:
    """Useful, secret-free diagnostics for one execution."""
    duration = None
    if record.started_at is not None:
        end = record.finished_at or time.time()
        duration = round(end - record.started_at, 3)
    return redact_secrets(
        {
            "execution_id": record.execution_id,
            "task_id": record.task_id,
            "session_id": record.session_id,
            "agent_id": record.agent_id,
            "status": record.status.value if hasattr(record.status, "value") else str(record.status),
            "capabilities": sorted(record.capabilities),
            "is_terminal": record.is_terminal(),
            "error": record.error,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
            "duration_seconds": duration,
            "checkpoint_keys": sorted((record.checkpoint or {}).keys()),
            "metadata_keys": sorted((record.metadata or {}).keys()),
            "workspace_id": getattr(record.workspace, "workspace_id", None),
        }
    )


def structured_log(
    level: str,
    message: str,
    **fields: Any,
) -> None:
    """Emit a structured log line with redacted extras."""
    extra = safe_log_extra(fields)
    log_fn = getattr(logger, level, logger.info)
    # stdlib Logger expects 'extra' to be a mapping of attributes; keep message rich.
    log_fn("%s | %s", message, extra)


def health_payload(
    *,
    service: str = "yasin-agent",
    version: str = "1.1.0",
    executions: int = 0,
    started_at: Optional[float] = None,
    ready: bool = True,
) -> Dict[str, Any]:
    now = time.time()
    return {
        "status": "healthy" if ready else "not_ready",
        "service": service,
        "version": version,
        "executions": executions,
        "uptime_seconds": round(now - (started_at or now), 3),
        "ready": ready,
        "metrics": get_metrics().snapshot(),
    }


def install_runtime_metrics(runtime: Any, metrics: Optional[RuntimeMetrics] = None) -> None:
    """
    Subscribe to ExecutionRuntime events and update metrics.

    Safe to call once per process; listeners must not break execution.
    Counts only primary lifecycle event types (not state_changed) to avoid
    double-counting.
    """
    m = metrics or get_metrics()

    def _dec_running() -> None:
        snap = m.snapshot()
        if snap["executions_running"] > 0:
            m.inc("executions_running", -1)

    def _on_event(event: Any) -> None:
        et = getattr(event, "event_type", "") or ""
        meta = getattr(event, "metadata", {}) or {}
        if et == "execution.created":
            m.inc("executions_created")
        elif et == "execution.started":
            m.inc("executions_running")
        elif et == "execution.completed":
            m.inc("executions_succeeded")
            _dec_running()
        elif et == "execution.failed":
            m.inc("executions_failed")
            _dec_running()
        elif et == "execution.cancelled":
            m.inc("executions_cancelled")
            _dec_running()
        elif et == "execution.paused":
            m.inc("executions_paused")
            _dec_running()
        elif et == "execution.resumed":
            m.inc("executions_running")
        elif et == "ai.capability" and meta.get("success") is False:
            m.inc("ai_capability_failures")
        elif et == "research.search" and meta.get("success") is False:
            m.inc("research_failures")

    runtime.events.subscribe(_on_event)


__all__ = [
    "ErrorClass",
    "RuntimeMetrics",
    "get_metrics",
    "correlation_context",
    "safe_log_extra",
    "classify_error",
    "execution_diagnostics",
    "structured_log",
    "health_payload",
    "install_runtime_metrics",
]
