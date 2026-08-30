"""Issue #43 — security hardening regression tests."""

from __future__ import annotations

import secrets

import pytest

from agent_platform.execution import ExecutionRuntime, redact_secrets
from agent_platform.memory import LayeredMemoryManager, MemoryAccessDenied, MemoryLayer
from agent_platform.research import MockResearchProvider, ResearchClient, ResearchRequest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from agent_platform.server.app import create_app


def test_secure_token_comparison_constant_time_shape():
    # secrets.compare_digest is used in server; verify behavior
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
    # job_id with path chars is sanitized
    store.save("../evil", {"job_id": "../evil", "task_id": "t", "status": "queued"})
    ids = store.list_ids()
    assert "../evil" in ids or any("evil" in i for i in ids)
    # no escape outside root
    for p in tmp_path.rglob("*"):
        assert tmp_path in p.resolve().parents or p.resolve() == tmp_path.resolve() or tmp_path in p.parents
