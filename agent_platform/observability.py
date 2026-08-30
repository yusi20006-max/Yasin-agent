"""
observability.py — Production observability + execution diagnostics (Issue #42).

Dependency-light: structured counters/gauges, correlation helpers, health
payloads. Secrets never logged.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .execution import redact_secrets


@dataclass
class RuntimeMetrics:
    """In-process counters and gauges for operational visibility."""

    executions_created: int = 0
    executions_running: int = 0
    executions_succeeded: int = 0
    executions_failed: int = 0
    executions_cancelled: int = 0
    scheduler_failures: int = 0
    http_errors: int = 0
    ai_capability_failures: int = 0
    research_failures: int = 0
    total_execution_duration_seconds: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def inc(self, name: str, value: int = 1) -> None:
        with self._lock:
            cur = getattr(self, name, None)
            if isinstance(cur, int):
                setattr(self, name, cur + value)

    def add_duration(self, seconds: float) -> None:
        with self._lock:
            self.total_execution_duration_seconds += max(0.0, seconds)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "executions_created": self.executions_created,
                "executions_running": self.executions_running,
                "executions_succeeded": self.executions_succeeded,
                "executions_failed": self.executions_failed,
                "executions_cancelled": self.executions_cancelled,
                "scheduler_failures": self.scheduler_failures,
                "http_errors": self.http_errors,
                "ai_capability_failures": self.ai_capability_failures,
                "research_failures": self.research_failures,
                "total_execution_duration_seconds": round(
                    self.total_execution_duration_seconds, 3
                ),
            }


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


def health_payload(
    *,
    service: str = "yasin-agent",
    version: str = "1.0.0",
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


__all__ = [
    "RuntimeMetrics",
    "get_metrics",
    "correlation_context",
    "safe_log_extra",
    "health_payload",
]
