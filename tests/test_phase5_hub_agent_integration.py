"""Phase 5: final YasinHub ↔ Yasin-Agent integration contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_platform.execution import ExecutionRuntime
from agent_platform.hub_contract import (
    CONTRACT_VERSION,
    EXECUTION_STATES,
    HEADER_CONTRACT,
    HEALTH_PATH,
    READY_PATH,
    is_terminal,
)

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from agent_platform.server.app import create_app

TOKEN = "test-service-token-phase5"
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


def test_hub_contract_version_and_states():
    assert CONTRACT_VERSION == "1.0"
    assert "running" in EXECUTION_STATES
    assert is_terminal("succeeded")
    assert is_terminal("failed")
    assert not is_terminal("running")
    assert HEALTH_PATH == "/v1/health"
    assert READY_PATH == "/v1/ready"


def test_no_duplicate_control_plane_modules():
    banned = ("pid_store", "service_manager", "start_service", "stop_service")
    for path in (ROOT / "agent_platform" / "server").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, f"{path} must not implement Hub lifecycle ({token})"


def test_health_and_ready_include_contract(client: TestClient):
    r = client.get("/v1/health", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body.get("ready") is True
    assert body.get("contract_version") == CONTRACT_VERSION
    assert r.headers.get(HEADER_CONTRACT) == CONTRACT_VERSION

    r2 = client.get("/v1/ready", headers=_auth())
    assert r2.status_code == 200
    assert r2.json()["ready"] is True
    assert r2.json().get("contract_version") == CONTRACT_VERSION


def test_health_requires_auth_fail_closed(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code in (401, 403)


def test_execution_lifecycle_truthful(client: TestClient):
    r = client.post(
        "/v1/executions",
        headers=_auth(**{"X-Request-Id": "p5-1"}),
        json={"task_id": "p5-task", "start": True, "capabilities": ["read"]},
    )
    assert r.status_code in (200, 201)
    body = r.json()
    assert body.get("task_id") == "p5-task"
    status = str(body.get("status") or "").lower()
    assert status in EXECUTION_STATES or status in {"queued", "running", "succeeded"}
    assert status != "completed"


def test_agent_restart_recovers_durable_execution(tmp_path):
    from agent_platform.persistence import JsonFileExecutionStore

    store = JsonFileExecutionStore(tmp_path / "exec")
    rt1 = ExecutionRuntime(store=store)
    c1 = TestClient(create_app(runtime=rt1, service_token=TOKEN))
    r = c1.post(
        "/v1/executions",
        headers=_auth(),
        json={"task_id": "recover-me", "start": True, "capabilities": ["read"]},
    )
    assert r.status_code == 201
    eid = r.json()["execution_id"]

    rt2 = ExecutionRuntime(store=store)
    c2 = TestClient(create_app(runtime=rt2, service_token=TOKEN))
    got = c2.get(f"/v1/executions/{eid}", headers=_auth())
    assert got.status_code == 200
    assert got.json()["execution_id"] == eid
    assert got.json()["task_id"] == "recover-me"


def test_ai_capability_boundary_not_provider_router():
    text = (ROOT / "agent_platform" / "ai_capability.py").read_text(encoding="utf-8")
    assert "CapabilityRequest" in text
    assert "CapabilityResponse" in text
    assert "OPENAI_API_KEY" not in text
    assert "sk-" not in text


def test_hub_client_sends_contract_header():
    from agent_platform.server.hub_client import HubAgentClient

    client = HubAgentClient(base_url="http://127.0.0.1:9", token="secret")
    headers = client._headers(request_id="rid-1")
    assert headers.get(HEADER_CONTRACT) == CONTRACT_VERSION
    assert headers["Authorization"].startswith("Bearer ")
