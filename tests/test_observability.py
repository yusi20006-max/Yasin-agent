"""Issue #42 — observability + diagnostics."""

from __future__ import annotations

from agent_platform.execution import ExecutionRuntime
from agent_platform.observability import (
    classify_error,
    correlation_context,
    execution_diagnostics,
    get_metrics,
    health_payload,
    install_runtime_metrics,
    safe_log_extra,
    structured_log,
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


def test_classify_error():
    assert classify_error(status_code=401) == "auth"
    assert classify_error(status_code=404) == "not_found"
    assert classify_error(status_code=409) == "conflict"
    assert classify_error(error_code="timeout") == "timeout"
    assert classify_error(error_code="capability.denied") == "capability"


def test_execution_diagnostics_secret_free():
    rt = ExecutionRuntime()
    rec = rt.create(task_id="t", metadata={"api_key": "sk-abc", "note": "x"})
    rt.start(rec.execution_id)
    d = execution_diagnostics(rt.get(rec.execution_id))
    assert d["execution_id"] == rec.execution_id
    assert d["status"] == "running"
    assert "api_key" not in d  # only metadata_keys listed
    assert "note" in d["metadata_keys"] or "api_key" in d["metadata_keys"]
    # raw secrets must not appear as values
    assert "sk-abc" not in str(d)


def test_install_runtime_metrics_lifecycle():
    m = get_metrics()
    m.reset()
    rt = ExecutionRuntime()
    install_runtime_metrics(rt, metrics=m)
    rec = rt.create(task_id="m1")
    assert m.snapshot()["executions_created"] == 1
    rt.start(rec.execution_id)
    assert m.snapshot()["executions_running"] == 1
    rt.complete(rec.execution_id)
    snap = m.snapshot()
    assert snap["executions_succeeded"] == 1
    assert snap["executions_running"] == 0


def test_structured_log_does_not_raise():
    structured_log("info", "test-message", request_id="r1", token="secret")
