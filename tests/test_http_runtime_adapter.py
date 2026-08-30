"""HTTP Execution Runtime adapter tests (Issue #38)."""
from __future__ import annotations

import importlib

import pytest

from agent_platform.execution import ExecutionRuntime

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from agent_platform.server.app import create_app

TOKEN = "test-service-token-38"


@pytest.fixture()
def runtime() -> ExecutionRuntime:
    return ExecutionRuntime()


@pytest.fixture()
def client(runtime: ExecutionRuntime) -> TestClient:
    app = create_app(runtime=runtime, service_token=TOKEN)
    return TestClient(app)


def _auth(**extra):
    h = {"Authorization": f"Bearer {TOKEN}"}
    h.update(extra)
    return h


def test_core_package_imports_without_http_extra() -> None:
    mod = importlib.import_module("agent_platform")
    assert hasattr(mod, "ExecutionRuntime")
    assert mod.__version__


def test_health_requires_auth(client: TestClient) -> None:
    r = client.get("/v1/health")
    assert r.status_code == 401


def test_health_rejects_invalid_token(client: TestClient) -> None:
    r = client.get("/v1/health", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_health_ok(client: TestClient) -> None:
    rid = "req-health-1"
    r = client.get("/v1/health", headers=_auth(**{"X-Request-Id": rid}))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert body["service"] == "yasin-agent"
    assert r.headers.get("X-Request-Id") == rid


def test_execution_list_get_and_events(client: TestClient, runtime: ExecutionRuntime) -> None:
    rec = runtime.create(task_id="task-a", agent_id="agent-1", metadata={"worker_id": "w1"})
    runtime.start(rec.execution_id)

    r = client.get("/v1/executions", headers=_auth())
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(i["execution_id"] == rec.execution_id for i in items)

    r = client.get(f"/v1/executions/{rec.execution_id}", headers=_auth())
    assert r.status_code == 200
    assert r.json()["status"] == "running"
    assert r.json()["task_id"] == "task-a"

    r = client.get(f"/v1/executions/{rec.execution_id}/events", headers=_auth())
    assert r.status_code == 200
    events = r.json()["items"]
    assert len(events) >= 1
    assert all("event_id" in e for e in events)

    r = client.get("/v1/events", headers=_auth(), params={"task_id": "task-a"})
    assert r.status_code == 200
    assert len(r.json()["items"]) >= 1


def test_get_missing_execution(client: TestClient) -> None:
    r = client.get("/v1/executions/missing", headers=_auth())
    assert r.status_code == 404


def test_pause_resume_cancel(client: TestClient, runtime: ExecutionRuntime) -> None:
    rec = runtime.create(task_id="task-life")
    runtime.start(rec.execution_id)

    r = client.post(
        f"/v1/executions/{rec.execution_id}/pause",
        headers=_auth(**{"X-Request-Id": "req-pause", "Idempotency-Key": "idem-pause"}),
        json={"request_id": "req-pause", "actor": "hub"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "paused"

    r = client.post(
        f"/v1/executions/{rec.execution_id}/resume",
        headers=_auth(**{"Idempotency-Key": "idem-resume"}),
        json={"request_id": "req-resume"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "running"

    r = client.post(
        f"/v1/executions/{rec.execution_id}/cancel",
        headers=_auth(**{"Idempotency-Key": "idem-cancel"}),
        json={"request_id": "req-cancel"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


def test_invalid_lifecycle_transition(client: TestClient, runtime: ExecutionRuntime) -> None:
    rec = runtime.create(task_id="task-bad")
    r = client.post(
        f"/v1/executions/{rec.execution_id}/pause",
        headers=_auth(),
        json={},
    )
    assert r.status_code == 409
    assert "invalid" in r.json()["detail"].lower() or "transition" in r.json()["detail"].lower()


def test_secret_redaction_in_execution_payload(client: TestClient, runtime: ExecutionRuntime) -> None:
    rec = runtime.create(
        task_id="task-sec",
        metadata={"api_key": "sk-should-redact", "note": "ok"},
    )
    r = client.get(f"/v1/executions/{rec.execution_id}", headers=_auth())
    assert r.status_code == 200
    meta = r.json()["metadata"]
    assert meta.get("note") == "ok"
    assert meta.get("api_key") != "sk-should-redact"


def test_fleet_list_get_cancel(client: TestClient, runtime: ExecutionRuntime) -> None:
    a = runtime.create(task_id="fleet-1", metadata={"worker_id": "w-a"})
    b = runtime.create(task_id="fleet-1", metadata={"worker_id": "w-b"})
    runtime.start(a.execution_id)
    runtime.start(b.execution_id)

    r = client.get("/v1/fleets", headers=_auth())
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(f["task_id"] == "fleet-1" for f in items)

    r = client.get("/v1/fleets/fleet-1", headers=_auth())
    assert r.status_code == 200
    assert len(r.json()["workers"]) == 2

    r = client.post(
        "/v1/fleets/fleet-1/cancel",
        headers=_auth(**{"Idempotency-Key": "fleet-cancel-1"}),
        json={"request_id": "req-fleet"},
    )
    assert r.status_code == 200
    assert r.json()["task_id"] == "fleet-1"
    assert runtime.get(a.execution_id).status.value == "cancelled"
    assert runtime.get(b.execution_id).status.value == "cancelled"


def test_malformed_auth_scheme(client: TestClient) -> None:
    r = client.get("/v1/health", headers={"Authorization": "Token not-bearer"})
    assert r.status_code == 401


def test_filter_executions_by_status(client: TestClient, runtime: ExecutionRuntime) -> None:
    running = runtime.create(task_id="t-filter")
    runtime.start(running.execution_id)
    queued = runtime.create(task_id="t-filter")
    r = client.get("/v1/executions", headers=_auth(), params={"status": "running", "task_id": "t-filter"})
    assert r.status_code == 200
    ids = {i["execution_id"] for i in r.json()["items"]}
    assert running.execution_id in ids
    assert queued.execution_id not in ids


def test_create_execution_endpoint(client: TestClient, runtime: ExecutionRuntime) -> None:
    r = client.post(
        "/v1/executions",
        headers=_auth(**{"Idempotency-Key": "idem-create-1"}),
        json={
            "task_id": "hub-task-1",
            "agent_id": "agent-hub",
            "capabilities": ["read", "research"],
            "metadata": {"source": "hub"},
            "start": True,
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["task_id"] == "hub-task-1"
    assert body["status"] == "running"
    assert body["agent_id"] == "agent-hub"
    eid = body["execution_id"]

    # Idempotent replay
    r2 = client.post(
        "/v1/executions",
        headers=_auth(**{"Idempotency-Key": "idem-create-1"}),
        json={"task_id": "hub-task-1", "start": True},
    )
    assert r2.status_code == 201
    assert r2.json()["execution_id"] == eid

    # Get / events / pause / resume / cancel
    assert client.get(f"/v1/executions/{eid}", headers=_auth()).status_code == 200
    assert client.get(f"/v1/executions/{eid}/events", headers=_auth()).status_code == 200
    assert client.post(f"/v1/executions/{eid}/pause", headers=_auth(), json={}).status_code == 200
    assert client.post(f"/v1/executions/{eid}/resume", headers=_auth(), json={}).status_code == 200
    assert client.post(f"/v1/executions/{eid}/cancel", headers=_auth(), json={}).status_code == 200
    final = client.get(f"/v1/executions/{eid}", headers=_auth()).json()
    assert final["status"] == "cancelled"


def test_create_requires_task_id(client: TestClient) -> None:
    r = client.post("/v1/executions", headers=_auth(), json={})
    assert r.status_code == 400


def test_create_401(client: TestClient) -> None:
    r = client.post("/v1/executions", json={"task_id": "x"})
    assert r.status_code == 401


def test_e2e_hub_style_orchestration(client: TestClient) -> None:
    """Simulates YasinHub HttpAgentRuntimeAdapter flow."""
    # health
    assert client.get("/v1/health", headers=_auth()).status_code == 200
    # create
    r = client.post(
        "/v1/executions",
        headers=_auth(**{"X-Request-Id": "hub-req-1"}),
        json={"task_id": "orch-1", "start": True, "capabilities": ["read"]},
    )
    assert r.status_code == 201
    assert r.headers.get("X-Request-Id") == "hub-req-1"
    eid = r.json()["execution_id"]
    # list
    items = client.get("/v1/executions", headers=_auth()).json()["items"]
    assert any(i["execution_id"] == eid for i in items)
    # events
    ev = client.get("/v1/events", headers=_auth()).json()["items"]
    assert len(ev) >= 1
    # fleets
    fleets = client.get("/v1/fleets", headers=_auth()).json()["items"]
    assert isinstance(fleets, list)
