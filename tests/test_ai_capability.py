"""Issue #35 — Yasin-AI capability contract boundary."""

from __future__ import annotations

import pytest

from agent_platform.ai_capability import (
    CapabilityClient,
    CapabilityErrorCode,
    CapabilityName,
    CapabilityRequest,
    MockCapabilityProvider,
)
from agent_platform.execution import ExecutionRuntime


def test_mock_inference():
    client = CapabilityClient(MockCapabilityProvider())
    req = CapabilityRequest(capability=CapabilityName.INFERENCE, input="hi")
    resp = client.invoke(req)
    assert resp.success
    assert "infer" in str(resp.output)
    assert resp.provider == "mock"
    assert client.call_count == 1


def test_all_capabilities():
    client = CapabilityClient(MockCapabilityProvider())
    for cap in CapabilityName:
        resp = client.invoke(CapabilityRequest(capability=cap, input="x"))
        assert resp.success, cap


def test_provider_failure():
    client = CapabilityClient(MockCapabilityProvider(fail=True), max_retries=0)
    resp = client.invoke(
        CapabilityRequest(capability=CapabilityName.INFERENCE, input="x")
    )
    assert not resp.success
    assert resp.error_code == CapabilityErrorCode.PROVIDER_ERROR.value


def test_allowed_capabilities_gate():
    client = CapabilityClient(
        MockCapabilityProvider(),
        allowed_capabilities=["summarization"],
    )
    ok = client.invoke(
        CapabilityRequest(capability=CapabilityName.SUMMARIZATION, input="long text")
    )
    assert ok.success
    denied = client.invoke(
        CapabilityRequest(capability=CapabilityName.INFERENCE, input="x")
    )
    assert not denied.success
    assert denied.error_code == CapabilityErrorCode.UNAUTHORIZED.value


def test_execution_association():
    rt = ExecutionRuntime()
    events = []
    rt.events.subscribe(lambda e: events.append(e))
    client = CapabilityClient(MockCapabilityProvider(), runtime=rt)
    rec = rt.create(task_id="t", capabilities=["inference"])
    rt.start(rec.execution_id)
    resp = client.invoke(
        CapabilityRequest(
            capability=CapabilityName.INFERENCE,
            input="x",
            execution_id=rec.execution_id,
            agent_id="a1",
        )
    )
    assert resp.success
    assert any(e.event_type == "ai.capability" for e in events)


def test_capability_denied_by_execution():
    rt = ExecutionRuntime()
    client = CapabilityClient(MockCapabilityProvider(), runtime=rt)
    rec = rt.create(task_id="t", capabilities=["read"])  # no inference
    rt.start(rec.execution_id)
    resp = client.invoke(
        CapabilityRequest(
            capability=CapabilityName.INFERENCE,
            input="x",
            execution_id=rec.execution_id,
        )
    )
    assert not resp.success
    assert resp.error_code == CapabilityErrorCode.UNAUTHORIZED.value


def test_no_external_credentials_required():
    """Core path works without any API keys."""
    client = CapabilityClient()  # default mock
    resp = client.invoke(
        CapabilityRequest(capability=CapabilityName.EMBEDDING, input="vec")
    )
    assert resp.success
    assert isinstance(resp.output, list)


def test_request_response_schemas():
    req = CapabilityRequest(
        capability=CapabilityName.CLASSIFICATION,
        input="text",
        parameters={"labels": ["a", "b"]},
        timeout_seconds=5.0,
    )
    d = req.as_dict()
    assert d["capability"] == "classification"
    assert d["contract_version"] == "1.0"
    client = CapabilityClient()
    resp = client.invoke(req)
    rd = resp.as_dict()
    assert "success" in rd
    assert rd["request_id"] == req.request_id


def test_secret_redaction_in_request():
    req = CapabilityRequest(
        capability=CapabilityName.INFERENCE,
        input="hi",
        metadata={"api_key": "sk-secretsecretsecret"},
    )
    d = req.as_dict()
    assert d["metadata"]["api_key"] == "***"
