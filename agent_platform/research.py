"""
research.py — Research / information-access capability boundary (Issue #36).

Research is an explicit capability, not uncontrolled network access.
Providers are replaceable; credentials stay outside source code.
Operations are associated with executions and emit audit events.
"""

from __future__ import annotations

import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from .execution import EventEmitter, ExecutionRuntime, redact_secrets


class ResearchErrorCode(str, Enum):
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    ACCESS_DENIED = "access_denied"
    MALFORMED = "malformed"
    EMPTY = "empty"
    CANCELLED = "cancelled"
    INTERNAL = "internal"


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
    max_results: int = 5
    timeout_seconds: float = 15.0
    execution_id: Optional[str] = None
    agent_id: Optional[str] = None
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
            }
        )


class ResearchProvider(ABC):
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
            )
        if self.empty:
            return ResearchResult(
                request_id=request.request_id,
                success=True,
                sources=[],
                provider=self.name,
                provenance={"mode": "empty"},
            )
        if self.malformed:
            # Simulate provider returning unusable data — boundary normalizes.
            return ResearchResult(
                request_id=request.request_id,
                success=False,
                error_code=ResearchErrorCode.MALFORMED.value,
                error_message="malformed provider payload",
                provider=self.name,
            )
        sources = [
            ResearchSource(
                url=f"https://example.test/{i}",
                title=f"Result {i} for {request.query}",
                snippet=f"Snippet about {request.query}",
                published_at="2026-01-01",
                provider=self.name,
                confidence=0.8 - i * 0.1,
            )
            for i in range(min(request.max_results, 3))
        ]
        return ResearchResult(
            request_id=request.request_id,
            success=True,
            sources=sources,
            provider=self.name,
            latency_ms=2.0,
            provenance={"query": request.query, "mode": "mock"},
        )


class ResearchClient:
    """
    Explicit research boundary.

    - Access control via execution capabilities / allowed flag
    - Timeout tagging
    - Normalized errors
    - Audit events
    - No arbitrary unrestricted network from agents
    """

    def __init__(
        self,
        provider: Optional[ResearchProvider] = None,
        *,
        runtime: Optional[ExecutionRuntime] = None,
        emitter: Optional[EventEmitter] = None,
        require_capability: str = "research",
        enabled: bool = True,
    ) -> None:
        self._provider = provider or MockResearchProvider()
        self._runtime = runtime
        self._emitter = emitter or (runtime.events if runtime else EventEmitter())
        self._require_capability = require_capability
        self._enabled = enabled
        self._lock = threading.Lock()
        self._call_count = 0

    def search(self, request: ResearchRequest) -> ResearchResult:
        start = time.time()
        if not self._enabled:
            result = ResearchResult(
                request_id=request.request_id,
                success=False,
                error_code=ResearchErrorCode.ACCESS_DENIED.value,
                error_message="research capability disabled",
                provider=getattr(self._provider, "name", "unknown"),
            )
            self._emit(request, result, start)
            return result

        if self._runtime and request.execution_id:
            try:
                self._runtime.check_capability(
                    request.execution_id, self._require_capability
                )
            except Exception as exc:
                result = ResearchResult(
                    request_id=request.request_id,
                    success=False,
                    error_code=ResearchErrorCode.ACCESS_DENIED.value,
                    error_message=str(exc),
                    provider=getattr(self._provider, "name", "unknown"),
                )
                self._emit(request, result, start)
                return result

        try:
            result = self._provider.search(request)
            if result.latency_ms is None:
                result.latency_ms = (time.time() - start) * 1000
            if result.success and not result.sources:
                # empty is still success unless provider said otherwise
                result.provenance = dict(result.provenance or {})
                result.provenance.setdefault("note", "empty_result")
        except Exception as exc:
            result = ResearchResult(
                request_id=request.request_id,
                success=False,
                error_code=ResearchErrorCode.PROVIDER_ERROR.value,
                error_message=str(exc),
                provider=getattr(self._provider, "name", "unknown"),
                latency_ms=(time.time() - start) * 1000,
            )
        with self._lock:
            self._call_count += 1
        self._emit(request, result, start)
        return result

    def _emit(
        self, request: ResearchRequest, result: ResearchResult, start: float
    ) -> None:
        meta: Dict[str, Any] = {
            "request_id": request.request_id,
            "success": result.success,
            "provider": result.provider,
            "source_count": len(result.sources),
            "latency_ms": result.latency_ms
            or (time.time() - start) * 1000,
        }
        if result.error_code:
            meta["error_code"] = result.error_code
        if result.provenance:
            meta["provenance"] = result.provenance
        self._emitter.emit(
            "research.search",
            execution_id=request.execution_id or "",
            task_id=request.metadata.get("task_id", ""),
            session_id=request.metadata.get("session_id", ""),
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
    "ResearchClient",
]
