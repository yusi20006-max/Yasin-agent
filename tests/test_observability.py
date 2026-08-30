"""Issue #42 — observability + diagnostics."""

from __future__ import annotations

from agent_platform.observability import (
    correlation_context,
    get_metrics,
    health_payload,
    safe_log_extra,
)


def test_metrics_counters():
    m = get_metrics()
    before = m.snapshot()["executions_created"]
    m.inc("executions_created")
    assert m.snapshot()["executions_created"] == before + 1


def test_correlation_context():
    ctx = correlation_context(request_id="r1", execution_id="e1", agent_id="a")
    assert ctx["request_id"] == "r1"
    assert "job_id" not in ctx


def test_safe_log_extra_redacts():
    extra = safe_log_extra({"api_key": "sk-secret", "ok": 1})
    assert extra["api_key"] == "***"
    assert extra["ok"] == 1


def test_health_payload():
    p = health_payload(executions=3, started_at=0)
    assert p["status"] == "healthy"
    assert p["ready"] is True
    assert "metrics" in p
