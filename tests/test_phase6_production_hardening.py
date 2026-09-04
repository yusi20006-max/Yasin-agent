"""Phase 6: production hardening regressions (idempotency, recovery, security, packaging)."""

from __future__ import annotations

import concurrent.futures
import json
import os
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from agent_platform.execution import ExecutionRuntime
from agent_platform.hub_contract import CONTRACT_VERSION, HEADER_CONTRACT
from agent_platform.persistence import JsonFileExecutionStore
from agent_platform.security import MAX_JSON_BODY_BYTES
from agent_platform.server.app import create_app, main

TOKEN = "phase6-service-token"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def runtime() -> ExecutionRuntime:
    return ExecutionRuntime()


@pytest.fixture()
def client(runtime: ExecutionRuntime) -> TestClient:
    return TestClient(create_app(runtime=runtime, service_token=TOKEN))


def _auth(**extra):
    h = {"Authorization": f"Bearer {TOKEN}"}
    h.update(extra)
    return h


def test_idempotent_create_returns_same_execution(client: TestClient):
    headers = _auth(**{"Idempotency-Key": "p6-idem-1", "X-Request-Id": "p6-r1"})
    body = {"task_id": "p6-task", "start": True, "capabilities": ["read"]}
    r1 = client.post("/v1/executions", headers=headers, json=body)
    r2 = client.post("/v1/executions", headers=headers, json=body)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["execution_id"] == r2.json()["execution_id"]


def test_concurrent_idempotent_create_single_execution(runtime: ExecutionRuntime):
    """Concurrent retries with the same Idempotency-Key must not double-create."""
    app = create_app(runtime=runtime, service_token=TOKEN)
    client = TestClient(app)

    def once():
        return client.post(
            "/v1/executions",
            headers=_auth(**{"Idempotency-Key": "p6-concurrent"}),
            json={"task_id": "p6-c", "start": False, "capabilities": ["read"]},
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: once(), range(12)))

    assert all(r.status_code == 201 for r in results)
    eids = {r.json()["execution_id"] for r in results}
    assert len(eids) == 1
    listed = client.get("/v1/executions", headers=_auth(), params={"task_id": "p6-c"})
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1


def test_corrupt_store_does_not_crash_recovery(tmp_path):
    store = JsonFileExecutionStore(tmp_path / "exec")
    store.save("good", {"execution_id": "good", "status": "succeeded", "task_id": "t"})
    bad = tmp_path / "exec" / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    (tmp_path / "exec" / "orphan.json.tmp").write_text("partial", encoding="utf-8")
    assert store.load("good") is not None
    assert store.load("bad") is None
    ids = store.list_ids()
    assert "good" in ids
    assert not list((tmp_path / "exec").glob("*.json.tmp"))


def test_oversized_body_rejected(client: TestClient):
    huge = "x" * (MAX_JSON_BODY_BYTES + 1024)
    r = client.post(
        "/v1/executions",
        headers={**_auth(), "Content-Length": str(len(huge) + 50)},
        content=json.dumps({"task_id": "big", "capabilities": ["read"], "pad": huge}),
    )
    assert r.status_code in (413, 400, 422)


def test_empty_service_token_rejects_protected_routes():
    app = create_app(runtime=ExecutionRuntime(), service_token="")
    c = TestClient(app)
    r = c.get("/v1/health")
    assert r.status_code in (401, 503)
    r2 = c.get("/v1/health", headers={"Authorization": "Bearer anything"})
    assert r2.status_code in (401, 503)


def test_diagnostics_are_secret_free(client: TestClient, runtime: ExecutionRuntime):
    rec = runtime.create(
        task_id="diag-t",
        capabilities=["read"],
        metadata={"Authorization": "Bearer secret-token-value", "note": "ok"},
    )
    r = client.get(f"/v1/executions/{rec.execution_id}/diagnostics", headers=_auth())
    assert r.status_code == 200
    dumped = json.dumps(r.json())
    assert "secret-token-value" not in dumped
    assert "Bearer secret" not in dumped


def test_ready_includes_contract_and_system(client: TestClient):
    r = client.get("/v1/ready", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body.get("ready") is True
    assert body.get("contract_version") == CONTRACT_VERSION
    assert r.headers.get(HEADER_CONTRACT) == CONTRACT_VERSION
    assert "system" in body


def test_no_second_control_plane_symbols():
    banned = ("pid_store", "ProcessSupervisor", "start_service", "stop_service")
    for path in (ROOT / "agent_platform").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, f"{path} must not contain {token}"


def test_packaging_entrypoint_and_version():
    import agent_platform

    assert agent_platform.__version__
    assert callable(main)
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'yasin-agent-server = "agent_platform.server.app:main"' in pyproject
    assert 'requires-python = ">=3.9"' in pyproject


def test_hub_contract_header_on_all_health_paths(client: TestClient):
    for path in ("/v1/health", "/v1/ready"):
        r = client.get(path, headers=_auth())
        assert r.status_code == 200
        assert r.headers.get(HEADER_CONTRACT) == CONTRACT_VERSION


def test_terminal_execution_not_restarted_by_recover(tmp_path):
    store = JsonFileExecutionStore(tmp_path / "ex")
    rt1 = ExecutionRuntime(store=store)
    rec = rt1.create(task_id="term", capabilities=["read"])
    rt1.start(rec.execution_id)
    rt1.complete(rec.execution_id, result={"ok": True})
    rt2 = ExecutionRuntime(store=store)
    recovered = rt2.recover(rec.execution_id)
    assert recovered is not None
    assert recovered.status.value == "succeeded"
    with pytest.raises(Exception):
        rt2.start(rec.execution_id)
