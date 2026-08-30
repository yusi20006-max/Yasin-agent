"""Issue #36 — research / information-access boundary."""

from __future__ import annotations

import pytest

from agent_platform.execution import ExecutionRuntime
from agent_platform.research import (
    MockResearchProvider,
    ResearchClient,
    ResearchErrorCode,
    ResearchRequest,
)


def test_successful_research():
    client = ResearchClient(MockResearchProvider())
    result = client.search(ResearchRequest(query="yasin ecosystem"))
    assert result.success
    assert len(result.sources) > 0
    assert result.sources[0].url is not None
    assert result.provenance


def test_provider_failure():
    client = ResearchClient(MockResearchProvider(fail=True))
    result = client.search(ResearchRequest(query="x"))
    assert not result.success
    assert result.error_code == ResearchErrorCode.PROVIDER_ERROR.value


def test_empty_result():
    client = ResearchClient(MockResearchProvider(empty=True))
    result = client.search(ResearchRequest(query="x"))
    assert result.success
    assert result.sources == []


def test_malformed_result():
    client = ResearchClient(MockResearchProvider(malformed=True))
    result = client.search(ResearchRequest(query="x"))
    assert not result.success
    assert result.error_code == ResearchErrorCode.MALFORMED.value


def test_access_denied_without_capability():
    rt = ExecutionRuntime()
    client = ResearchClient(MockResearchProvider(), runtime=rt)
    rec = rt.create(task_id="t", capabilities=["read"])
    rt.start(rec.execution_id)
    result = client.search(
        ResearchRequest(query="x", execution_id=rec.execution_id)
    )
    assert not result.success
    assert result.error_code == ResearchErrorCode.ACCESS_DENIED.value


def test_access_granted_with_capability():
    rt = ExecutionRuntime()
    client = ResearchClient(MockResearchProvider(), runtime=rt)
    rec = rt.create(task_id="t", capabilities=["research"])
    rt.start(rec.execution_id)
    result = client.search(
        ResearchRequest(query="x", execution_id=rec.execution_id)
    )
    assert result.success


def test_disabled_client():
    client = ResearchClient(MockResearchProvider(), enabled=False)
    result = client.search(ResearchRequest(query="x"))
    assert not result.success
    assert result.error_code == ResearchErrorCode.ACCESS_DENIED.value


def test_execution_association_events():
    rt = ExecutionRuntime()
    events = []
    rt.events.subscribe(lambda e: events.append(e))
    client = ResearchClient(MockResearchProvider(), runtime=rt)
    rec = rt.create(task_id="t", capabilities=["research"])
    rt.start(rec.execution_id)
    client.search(
        ResearchRequest(query="yasin", execution_id=rec.execution_id, agent_id="a")
    )
    assert any(e.event_type == "research.search" for e in events)


def test_provenance_present():
    client = ResearchClient(MockResearchProvider())
    result = client.search(ResearchRequest(query="provenance-check"))
    assert result.provenance.get("query") == "provenance-check"
    assert result.retrieved_at > 0


def test_no_credentials_in_code_path():
    client = ResearchClient()
    assert client.search(ResearchRequest(query="ok")).success
