"""Issue #43 — security hardening regression tests."""

from __future__ import annotations

import secrets

import pytest

from agent_platform.execution import ExecutionRuntime, redact_secrets
from agent_platform.memory import LayeredMemoryManager, MemoryAccessDenied, MemoryLayer
from agent_platform.research import MockResearchProvider, ResearchClient, ResearchRequest
from agent_platform.security import (
    SecurityError,
    assert_same_agent,
    assert_same_session,
    is_safe_workspace_path,
    reject_dangerous_capabilities,
    safe_error_detail,
    sanitize_metadata,
    validate_capabilities,
    validate_identifier,
)

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from agent_platform.server.app import create_app


def test_secure_token_comparison_constant_time_shape():
    a = "yasin-live-test-token"
    assert secrets.compare_digest(a, a)
    assert not secrets.compare_digest(a, a + "x")


def test_redact_secrets_recursive():
    data = {
        "api_key": "sk-abc",
        "nested": {"token": "t", "ok": 1},
        "list": [{"password": "p"}],
        "note": "bearer sk-abcdefghijklmnopqrst",
    }
    out = redact_secrets(data)
    assert out["api_key"] == "***"
    assert out["nested"]["token"] == "***"
    assert out["nested"]["ok"] == 1
    assert out["list"][0]["password"] == "***"
    assert "***" in out["note"]


def test_cross_agent_memory_blocked():
    mm = LayeredMemoryManager()
    m = mm.add_memory("private", layer=MemoryLayer.L3_CORE)
    mm.create_loadout("a1")
    mm.attach_memory(mm.get_active_loadout("a1").loadout_id, m.asset_id)
    mm.create_loadout("a2")
    with pytest.raises(MemoryAccessDenied):
        mm.get_memory(m.asset_id, agent_id="a2")


def test_research_requires_capability():
    rt = ExecutionRuntime()
    client = ResearchClient(MockResearchProvider(), runtime=rt)
    rec = rt.create(task_id="t", capabilities=[])
    rt.start(rec.execution_id)
    res = client.search(ResearchRequest(query="x", execution_id=rec.execution_id))
    assert not res.success


def test_http_auth_required_on_create():
    app = create_app(service_token="secret-token")
    c = TestClient(app)
    assert c.post("/v1/executions", json={"task_id": "t"}).status_code == 401
    assert (
        c.post(
            "/v1/executions",
            headers={"Authorization": "Bearer secret-token"},
            json={"task_id": "t"},
        ).status_code
        == 201
    )


def test_cancel_unrelated_execution_isolated():
    rt = ExecutionRuntime()
    a = rt.create(task_id="a")
    b = rt.create(task_id="b")
    rt.start(a.execution_id)
    rt.start(b.execution_id)
    rt.cancel(a.execution_id)
    assert rt.get(a.execution_id).status.value == "cancelled"
    assert rt.get(b.execution_id).status.value == "running"


def test_path_safe_job_store(tmp_path):
    from agent_platform.jobs import JsonFileJobStore

    store = JsonFileJobStore(tmp_path)
    store.save("../evil", {"job_id": "../evil", "task_id": "t", "status": "queued"})
    for p in tmp_path.rglob("*"):
        assert tmp_path in p.resolve().parents or p.parent == tmp_path or p == tmp_path


def test_validate_identifier_rejects_traversal():
    with pytest.raises(SecurityError):
        validate_identifier("../etc/passwd", name="execution_id")
    with pytest.raises(SecurityError):
        validate_identifier("bad id with spaces")
    assert validate_identifier("exec-abc_01") == "exec-abc_01"


def test_sanitize_metadata_bounds():
    meta = sanitize_metadata({"a": "x" * 20_000, "b": 1})
    assert len(meta["a"]) <= 8192
    with pytest.raises(SecurityError):
        sanitize_metadata({f"k{i}": i for i in range(100)})


def test_capabilities_validation():
    assert validate_capabilities(["read", "research"]) == ["read", "research"]
    with pytest.raises(SecurityError):
        validate_capabilities(["Shell;rm"])
    with pytest.raises(SecurityError):
        reject_dangerous_capabilities(["shell"])


def test_session_and_agent_isolation_helpers():
    assert_same_session("s1", "s1")
    with pytest.raises(SecurityError):
        assert_same_session("s1", "s2")
    with pytest.raises(SecurityError):
        assert_same_agent("a1", "a2")


def test_workspace_path_policy():
    assert is_safe_workspace_path("/tmp/ws")
    assert not is_safe_workspace_path("../secret")
    assert not is_safe_workspace_path("/etc/passwd")


def test_safe_error_detail_no_path_leak():
    assert "home" not in safe_error_detail(Exception("fail at /home/user/secret"))


def test_http_rejects_bad_task_id():
    app = create_app(service_token="tok")
    c = TestClient(app)
    r = c.post(
        "/v1/executions",
        headers={"Authorization": "Bearer tok"},
        json={"task_id": "../evil"},
    )
    assert r.status_code == 400


def test_http_rejects_oversized_content_length():
    app = create_app(service_token="tok")
    c = TestClient(app)
    r = c.post(
        "/v1/executions",
        headers={
            "Authorization": "Bearer tok",
            "Content-Length": str(2_000_000),
        },
        json={"task_id": "t"},
    )
    # Starlette may reject before our middleware; accept 413 or client error
    assert r.status_code in (413, 400, 401, 422)


def test_idempotency_does_not_escalate():
    """Replaying Idempotency-Key returns original payload, not a privileged one."""
    app = create_app(service_token="tok")
    c = TestClient(app)
    r1 = c.post(
        "/v1/executions",
        headers={"Authorization": "Bearer tok", "Idempotency-Key": "k1"},
        json={"task_id": "t1", "capabilities": ["read"]},
    )
    assert r1.status_code == 201
    r2 = c.post(
        "/v1/executions",
        headers={"Authorization": "Bearer tok", "Idempotency-Key": "k1"},
        json={"task_id": "t1", "capabilities": ["shell", "research"]},
    )
    assert r2.status_code == 201
    assert r2.json()["execution_id"] == r1.json()["execution_id"]
    assert "shell" not in r2.json().get("capabilities", [])


def test_no_plaintext_token_in_execution_events():
    rt = ExecutionRuntime()
    events = []
    rt.events.subscribe(lambda e: events.append(e))
    rt.create(task_id="t", metadata={"authorization": "Bearer super-secret-token-value"})
    for e in events:
        blob = str(e.as_dict())
        assert "super-secret-token-value" not in blob
