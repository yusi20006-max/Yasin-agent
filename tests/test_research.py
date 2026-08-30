"""Issue #36 — research / information-access boundary."""

from __future__ import annotations

import pytest

from agent_platform.execution import ExecutionRuntime
from agent_platform.research import (
    MAX_RESULTS_HARD_LIMIT,
    MockResearchProvider,
    ResearchClient,
    ResearchErrorCode,
    ResearchProvider,
    ResearchRegistry,
    ResearchRequest,
    ResearchResult,
)
from agent_platform.tool_runner import ToolRunner


def test_successful_research():
    client = ResearchClient(MockResearchProvider())
    result = client.search(ResearchRequest(query="yasin ecosystem"))
    assert result.success
    assert len(result.sources) > 0
    assert result.sources[0].url is not None
    assert result.provenance


def test_provider_failure_isolated():
    client = ResearchClient(MockResearchProvider(fail=True), max_retries=0)
    result = client.search(ResearchRequest(query="x"))
    assert not result.success
    assert result.error_code == ResearchErrorCode.PROVIDER_ERROR.value
    client2 = ResearchClient(MockResearchProvider())
    assert client2.search(ResearchRequest(query="ok")).success


def test_empty_result():
    client = ResearchClient(MockResearchProvider(empty=True))
    result = client.search(ResearchRequest(query="x"))
    assert result.success
    assert result.sources == []


def test_malformed_result():
    client = ResearchClient(MockResearchProvider(malformed=True), max_retries=0)
    result = client.search(ResearchRequest(query="x"))
    assert not result.success
    assert result.error_code == ResearchErrorCode.MALFORMED.value


def test_access_denied_without_capability():
    rt = ExecutionRuntime()
    client = ResearchClient(MockResearchProvider(), runtime=rt)
    rec = rt.create(task_id="t", capabilities=["read"])
    rt.start(rec.execution_id)
    result = client.search(ResearchRequest(query="x", execution_id=rec.execution_id))
    assert not result.success
    assert result.error_code == ResearchErrorCode.ACCESS_DENIED.value


def test_access_granted_with_capability():
    rt = ExecutionRuntime()
    client = ResearchClient(MockResearchProvider(), runtime=rt)
    rec = rt.create(task_id="t", capabilities=["research"])
    rt.start(rec.execution_id)
    result = client.search(ResearchRequest(query="x", execution_id=rec.execution_id))
    assert result.success


def test_disabled_client():
    client = ResearchClient(MockResearchProvider(), enabled=False)
    result = client.search(ResearchRequest(query="x"))
    assert not result.success
    assert result.error_code == ResearchErrorCode.ACCESS_DENIED.value


def test_execution_session_worker_correlation():
    rt = ExecutionRuntime()
    events = []
    rt.events.subscribe(lambda e: events.append(e))
    client = ResearchClient(MockResearchProvider(), runtime=rt)
    rec = rt.create(task_id="t", session_id="sess-9", capabilities=["research"])
    rt.start(rec.execution_id)
    result = client.search(
        ResearchRequest(
            query="yasin",
            execution_id=rec.execution_id,
            session_id="sess-9",
            worker_id="w-1",
            agent_id="a",
        )
    )
    assert result.success
    assert result.execution_id == rec.execution_id
    assert result.session_id == "sess-9"
    assert result.worker_id == "w-1"
    assert any(e.event_type == "research.search" for e in events)
    ev = next(e for e in events if e.event_type == "research.search")
    assert ev.metadata.get("worker_id") == "w-1"


def test_provenance_present():
    client = ResearchClient(MockResearchProvider())
    result = client.search(ResearchRequest(query="provenance-check"))
    assert result.provenance.get("query") == "provenance-check"
    assert result.retrieved_at > 0


def test_no_credentials_in_code_path():
    client = ResearchClient()
    assert client.search(ResearchRequest(query="ok")).success


def test_provider_registration():
    class Alt(ResearchProvider):
        name = "alt"

        def search(self, request: ResearchRequest) -> ResearchResult:
            return ResearchResult(
                request_id=request.request_id,
                success=True,
                sources=[],
                provider="alt",
                provenance={"provider": "alt"},
            )

    reg = ResearchRegistry()
    client = ResearchClient(registry=reg, default_provider="alt")
    client.register_provider("alt", Alt())
    assert "alt" in client.list_providers()
    result = client.search(ResearchRequest(query="x"), provider="alt")
    assert result.success
    assert result.provider == "alt"


def test_unknown_provider():
    client = ResearchClient(MockResearchProvider())
    result = client.search(ResearchRequest(query="x"), provider="does-not-exist")
    assert not result.success
    assert result.error_code == ResearchErrorCode.PROVIDER_ERROR.value


def test_result_size_hard_limit():
    client = ResearchClient(MockResearchProvider())
    result = client.search(ResearchRequest(query="x", max_results=10_000))
    assert result.success
    assert len(result.sources) <= MAX_RESULTS_HARD_LIMIT
    assert len(result.sources) <= 3


def test_timeout():
    client = ResearchClient(MockResearchProvider(delay=0.05), max_retries=0)
    result = client.search(ResearchRequest(query="x", timeout_seconds=0.01))
    assert not result.success
    assert result.error_code == ResearchErrorCode.TIMEOUT.value


def test_retry_then_success():
    class Flaky(ResearchProvider):
        name = "flaky"

        def __init__(self) -> None:
            self.n = 0

        def search(self, request: ResearchRequest) -> ResearchResult:
            self.n += 1
            if self.n == 1:
                raise RuntimeError("transient")
            return ResearchResult(
                request_id=request.request_id,
                success=True,
                sources=[],
                provider="flaky",
            )

    client = ResearchClient(Flaky(), max_retries=1)
    assert client.search(ResearchRequest(query="x")).success


def test_tool_runner_integration_backward_compatible():
    tr = ToolRunner()
    tr.register("echo", lambda text, **_: text)
    assert tr.run("echo", text="hi") == "hi"

    client = ResearchClient(MockResearchProvider())
    client.register_on_tool_runner(tr, name="research")
    assert "research" in tr.list_tools()
    out = tr.run("research", query="yasin", context={"execution_id": None})
    assert out["success"] is True
    assert "sources" in out


def test_empty_query_rejected():
    client = ResearchClient(MockResearchProvider())
    result = client.search(ResearchRequest(query="  "))
    assert not result.success
    assert result.error_code == ResearchErrorCode.MALFORMED.value


def test_secret_redaction_in_result():
    src_result = ResearchResult(
        request_id="r1",
        success=True,
        sources=[],
        provenance={"api_key": "sk-secretsecret"},
    )
    d = src_result.as_dict()
    assert d["provenance"]["api_key"] == "***"
