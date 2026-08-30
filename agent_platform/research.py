"""
research.py — Research / information-access capability boundary (Issue #36).

External information access is an explicit, governed capability — not
unrestricted network access. Providers are pluggable; credentials stay
outside source, logs, and event payloads.

Contract:
  ResearchRequest  ->  ResearchProvider.search  ->  ResearchResult

Integrates with ExecutionRuntime (capability gate + correlation) and can
be registered on ToolRunner as a normal tool without changing ToolRunner
internals.
"""

from __future__ import annotations

import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence

from .execution import EventEmitter, ExecutionRuntime, redact_secrets


class ResearchErrorCode(str, Enum):
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    ACCESS_DENIED = "access_denied"
    MALFORMED = "malformed"
    EMPTY = "empty"
    CANCELLED = "cancelled"
    INTERNAL = "internal"
    LIMIT_EXCEEDED = "limit_exceeded"


# Hard bounds — callers cannot bypass these via request fields.
MAX_RESULTS_HARD_LIMIT = 50
MAX_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_RESULTS = 5
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_RETRIES = 1


@dataclass
class ResearchSource:
    url: Optional[str] = None
    title: Optional[str] = None
    snippet: Optional[str] = None
    published_at: Optional[str] = None
    provider: Optional[str] = None
    confidence: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return redact_secrets(
            {
                "url": self.url,
                "title": self.title,
                "snippet": self.snippet,
                "published_at": self.published_at,
                "provider": self.provider,
                "confidence": self.confidence,
                "metadata": dict(self.metadata),
            }
        )


@dataclass
class ResearchRequest:
    query: str
    max_results: int = DEFAULT_MAX_RESULTS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    execution_id: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    worker_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: f"resreq-{uuid.uuid4().hex[:12]}")

    def as_dict(self) -> Dict[str, Any]:
        return redact_secrets(
            {
                "query": self.query,
                "max_results": self.max_results,
                "timeout_seconds": self.timeout_seconds,
                "execution_id": self.execution_id,
                "agent_id": self.agent_id,
                "session_id": self.session_id,
                "worker_id": self.worker_id,
                "metadata": dict(self.metadata),
                "request_id": self.request_id,
            }
        )


@dataclass
class ResearchResult:
    request_id: str
    success: bool
    sources: List[ResearchSource] = field(default_factory=list)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    provider: Optional[str] = None
    latency_ms: Optional[float] = None
    retrieved_at: float = field(default_factory=time.time)
    provenance: Dict[str, Any] = field(default_factory=dict)
    execution_id: Optional[str] = None
    session_id: Optional[str] = None
    worker_id: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return redact_secrets(
            {
                "request_id": self.request_id,
                "success": self.success,
                "sources": [s.as_dict() for s in self.sources],
                "error_code": self.error_code,
                "error_message": self.error_message,
                "provider": self.provider,
                "latency_ms": self.latency_ms,
                "retrieved_at": self.retrieved_at,
                "provenance": dict(self.provenance),
                "execution_id": self.execution_id,
                "session_id": self.session_id,
                "worker_id": self.worker_id,
            }
        )


class ResearchProvider(ABC):
    """Stable provider interface. Register implementations by name."""

    name: str = "base"

    @abstractmethod
    def search(self, request: ResearchRequest) -> ResearchResult:
        ...


class MockResearchProvider(ResearchProvider):
    """In-process mock — no network, no credentials."""

    name = "mock"

    def __init__(
        self,
        *,
        fail: bool = False,
        empty: bool = False,
        malformed: bool = False,
        delay: float = 0.0,
    ) -> None:
        self.fail = fail
        self.empty = empty
        self.malformed = malformed
        self.delay = delay
        self.calls: List[ResearchRequest] = []

    def search(self, request: ResearchRequest) -> ResearchResult:
        self.calls.append(request)
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            return ResearchResult(
                request_id=request.request_id,
                success=False,
                error_code=ResearchErrorCode.PROVIDER_ERROR.value,
                error_message="mock provider failure",
                provider=self.name,
                execution_id=request.execution_id,
                session_id=request.session_id,
                worker_id=request.worker_id,
            )
        if self.empty:
            return ResearchResult(
                request_id=request.request_id,
                success=True,
                sources=[],
                provider=self.name,
                provenance={"mode": "empty", "query": request.query},
                execution_id=request.execution_id,
                session_id=request.session_id,
                worker_id=request.worker_id,
            )
        if self.malformed:
            return ResearchResult(
                request_id=request.request_id,
                success=False,
                error_code=ResearchErrorCode.MALFORMED.value,
                error_message="malformed provider payload",
                provider=self.name,
                execution_id=request.execution_id,
                session_id=request.session_id,
                worker_id=request.worker_id,
            )
        n = min(request.max_results, 3)
        sources = [
            ResearchSource(
                url=f"https://example.test/{i}",
                title=f"Result {i} for {request.query}",
                snippet=f"Snippet about {request.query}",
                published_at="2026-01-01",
                provider=self.name,
                confidence=max(0.0, 0.8 - i * 0.1),
            )
            for i in range(n)
        ]
        return ResearchResult(
            request_id=request.request_id,
            success=True,
            sources=sources,
            provider=self.name,
            latency_ms=2.0,
            provenance={"query": request.query, "mode": "mock"},
            execution_id=request.execution_id,
            session_id=request.session_id,
            worker_id=request.worker_id,
        )


class ResearchRegistry:
    """Named provider registry — pluggable behind a stable interface."""

    def __init__(self) -> None:
        self._providers: Dict[str, ResearchProvider] = {}
        self._lock = threading.RLock()

    def register(self, name: str, provider: ResearchProvider) -> None:
        if not name or not isinstance(name, str):
            raise ValueError("provider name is required")
        with self._lock:
            self._providers[name] = provider
            # Keep provider.name aligned for events.
            try:
                provider.name = name
            except Exception:
                pass

    def get(self, name: str) -> Optional[ResearchProvider]:
        with self._lock:
            return self._providers.get(name)

    def list_names(self) -> List[str]:
        with self._lock:
            return sorted(self._providers.keys())

    def unregister(self, name: str) -> None:
        with self._lock:
            self._providers.pop(name, None)


class ResearchClient:
    """
    Explicit research boundary.

    - Capability gate via ExecutionRuntime
    - Bounded max_results / timeout / retries
    - Provenance + execution/session/worker correlation
    - Isolated provider failures
    - Optional ToolRunner registration
    """

    def __init__(
        self,
        provider: Optional[ResearchProvider] = None,
        *,
        runtime: Optional[ExecutionRuntime] = None,
        emitter: Optional[EventEmitter] = None,
        require_capability: str = "research",
        enabled: bool = True,
        max_retries: int = DEFAULT_MAX_RETRIES,
        registry: Optional[ResearchRegistry] = None,
        default_provider: str = "mock",
    ) -> None:
        self._registry = registry or ResearchRegistry()
        if provider is not None:
            pname = getattr(provider, "name", None) or default_provider
            self._registry.register(pname, provider)
            default_provider = pname
        elif self._registry.get(default_provider) is None:
            self._registry.register(default_provider, MockResearchProvider())
        self._default_provider = default_provider
        self._runtime = runtime
        self._emitter = emitter or (runtime.events if runtime else EventEmitter())
        self._require_capability = require_capability
        self._enabled = enabled
        self._max_retries = max(0, int(max_retries))
        self._lock = threading.Lock()
        self._call_count = 0

    def register_provider(self, name: str, provider: ResearchProvider) -> None:
        self._registry.register(name, provider)

    def list_providers(self) -> List[str]:
        return self._registry.list_names()

    def search(
        self,
        request: ResearchRequest,
        *,
        provider: Optional[str] = None,
    ) -> ResearchResult:
        start = time.time()
        # Bound request parameters
        request.max_results = max(1, min(int(request.max_results or DEFAULT_MAX_RESULTS), MAX_RESULTS_HARD_LIMIT))
        request.timeout_seconds = max(
            0.01, min(float(request.timeout_seconds or DEFAULT_TIMEOUT_SECONDS), MAX_TIMEOUT_SECONDS)
        )

        if not self._enabled:
            result = ResearchResult(
                request_id=request.request_id,
                success=False,
                error_code=ResearchErrorCode.ACCESS_DENIED.value,
                error_message="research capability disabled",
                provider=provider or self._default_provider,
                execution_id=request.execution_id,
                session_id=request.session_id,
                worker_id=request.worker_id,
            )
            self._emit(request, result, start)
            return result

        if not (request.query or "").strip():
            result = ResearchResult(
                request_id=request.request_id,
                success=False,
                error_code=ResearchErrorCode.MALFORMED.value,
                error_message="query is required",
                provider=provider or self._default_provider,
                execution_id=request.execution_id,
                session_id=request.session_id,
                worker_id=request.worker_id,
            )
            self._emit(request, result, start)
            return result

        if self._runtime and request.execution_id:
            try:
                self._runtime.check_capability(request.execution_id, self._require_capability)
            except Exception as exc:
                result = ResearchResult(
                    request_id=request.request_id,
                    success=False,
                    error_code=ResearchErrorCode.ACCESS_DENIED.value,
                    error_message=str(exc),
                    provider=provider or self._default_provider,
                    execution_id=request.execution_id,
                    session_id=request.session_id,
                    worker_id=request.worker_id,
                )
                self._emit(request, result, start)
                return result

        pname = provider or self._default_provider
        prov = self._registry.get(pname)
        if prov is None:
            result = ResearchResult(
                request_id=request.request_id,
                success=False,
                error_code=ResearchErrorCode.PROVIDER_ERROR.value,
                error_message=f"unknown research provider: {pname}",
                provider=pname,
                execution_id=request.execution_id,
                session_id=request.session_id,
                worker_id=request.worker_id,
            )
            self._emit(request, result, start)
            return result

        last: Optional[ResearchResult] = None
        attempts = 1 + self._max_retries
        for attempt in range(1, attempts + 1):
            try:
                result = prov.search(request)
                elapsed = time.time() - start
                if result.latency_ms is None:
                    result.latency_ms = elapsed * 1000
                # Enforce timeout after provider returns (deterministic for tests)
                if elapsed > request.timeout_seconds:
                    result = ResearchResult(
                        request_id=request.request_id,
                        success=False,
                        error_code=ResearchErrorCode.TIMEOUT.value,
                        error_message=f"research timed out after {elapsed:.3f}s",
                        provider=getattr(prov, "name", pname),
                        latency_ms=elapsed * 1000,
                        execution_id=request.execution_id,
                        session_id=request.session_id,
                        worker_id=request.worker_id,
                        provenance={"attempt": attempt},
                    )
                # Cap returned sources
                if result.success and len(result.sources) > request.max_results:
                    result.sources = result.sources[: request.max_results]
                # Correlation fields
                result.execution_id = result.execution_id or request.execution_id
                result.session_id = result.session_id or request.session_id
                result.worker_id = result.worker_id or request.worker_id
                if result.success or attempt >= attempts:
                    with self._lock:
                        self._call_count += 1
                    self._emit(request, result, start)
                    return result
                last = result
            except Exception as exc:
                last = ResearchResult(
                    request_id=request.request_id,
                    success=False,
                    error_code=ResearchErrorCode.PROVIDER_ERROR.value,
                    error_message=str(exc),
                    provider=getattr(prov, "name", pname),
                    latency_ms=(time.time() - start) * 1000,
                    execution_id=request.execution_id,
                    session_id=request.session_id,
                    worker_id=request.worker_id,
                    provenance={"attempt": attempt},
                )
                if attempt >= attempts:
                    with self._lock:
                        self._call_count += 1
                    self._emit(request, last, start)
                    return last
        assert last is not None
        with self._lock:
            self._call_count += 1
        self._emit(request, last, start)
        return last

    def as_tool(self) -> Callable[..., Any]:
        """Return a ToolRunner-compatible callable."""

        def research_tool(
            query: str,
            *,
            max_results: int = DEFAULT_MAX_RESULTS,
            timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
            execution_id: Optional[str] = None,
            agent_id: Optional[str] = None,
            session_id: Optional[str] = None,
            worker_id: Optional[str] = None,
            provider: Optional[str] = None,
            context: Optional[Dict[str, Any]] = None,
            **_: Any,
        ) -> Dict[str, Any]:
            ctx = context or {}
            req = ResearchRequest(
                query=query,
                max_results=max_results,
                timeout_seconds=timeout_seconds,
                execution_id=execution_id or ctx.get("execution_id"),
                agent_id=agent_id or ctx.get("agent_id"),
                session_id=session_id or ctx.get("session_id"),
                worker_id=worker_id or ctx.get("worker_id"),
                metadata={"via": "tool_runner"},
            )
            return self.search(req, provider=provider).as_dict()

        return research_tool

    def register_on_tool_runner(self, tool_runner: Any, name: str = "research") -> None:
        """Register as a normal tool — does not change ToolRunner behavior."""
        tool_runner.register(name, self.as_tool())

    def _emit(self, request: ResearchRequest, result: ResearchResult, start: float) -> None:
        meta: Dict[str, Any] = {
            "request_id": request.request_id,
            "success": result.success,
            "provider": result.provider,
            "source_count": len(result.sources),
            "latency_ms": result.latency_ms or (time.time() - start) * 1000,
            "query_len": len(request.query or ""),
        }
        if result.error_code:
            meta["error_code"] = result.error_code
        if result.provenance:
            meta["provenance"] = result.provenance
        if request.worker_id:
            meta["worker_id"] = request.worker_id
        self._emitter.emit(
            "research.search",
            execution_id=request.execution_id or "",
            task_id=(request.metadata or {}).get("task_id", ""),
            session_id=request.session_id or (request.metadata or {}).get("session_id", "") or "",
            status="ok" if result.success else "error",
            metadata=meta,
            agent_id=request.agent_id,
        )

    @property
    def call_count(self) -> int:
        with self._lock:
            return self._call_count


__all__ = [
    "ResearchErrorCode",
    "ResearchSource",
    "ResearchRequest",
    "ResearchResult",
    "ResearchProvider",
    "MockResearchProvider",
    "ResearchRegistry",
    "ResearchClient",
    "MAX_RESULTS_HARD_LIMIT",
    "MAX_TIMEOUT_SECONDS",
]
