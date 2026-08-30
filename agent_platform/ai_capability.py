"""
ai_capability.py — Yasin-AI canonical capability contract boundary (Issue #35).

Yasin-Agent must NOT become a second independent AI platform.
Project / Agent → Versioned AI Capability Contract → Yasin-AI

Provider-independent interface with request/response schemas, timeout,
retry, error normalization, and observability. Core runtime remains usable
without Yasin-AI.
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


class CapabilityName(str, Enum):
    INFERENCE = "inference"
    STRUCTURED_GENERATION = "structured_generation"
    CLASSIFICATION = "classification"
    SUMMARIZATION = "summarization"
    TOOL_SELECTION = "tool_selection"
    EMBEDDING = "embedding"


class CapabilityErrorCode(str, Enum):
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    INVALID_REQUEST = "invalid_request"
    UNAUTHORIZED = "unauthorized"
    RATE_LIMITED = "rate_limited"
    NOT_SUPPORTED = "not_supported"
    CANCELLED = "cancelled"
    INTERNAL = "internal"


@dataclass
class CapabilityRequest:
    """Versioned capability request."""

    capability: CapabilityName
    contract_version: str = "1.0"
    input: Any = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_id: Optional[str] = None
    agent_id: Optional[str] = None
    request_id: str = field(default_factory=lambda: f"capreq-{uuid.uuid4().hex[:12]}")

    def as_dict(self) -> Dict[str, Any]:
        return redact_secrets(
            {
                "capability": self.capability.value
                if isinstance(self.capability, CapabilityName)
                else self.capability,
                "contract_version": self.contract_version,
                "input": self.input,
                "parameters": dict(self.parameters),
                "timeout_seconds": self.timeout_seconds,
                "metadata": dict(self.metadata),
                "execution_id": self.execution_id,
                "agent_id": self.agent_id,
                "request_id": self.request_id,
            }
        )


@dataclass
class CapabilityResponse:
    request_id: str
    capability: str
    success: bool
    output: Any = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    latency_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return redact_secrets(
            {
                "request_id": self.request_id,
                "capability": self.capability,
                "success": self.success,
                "output": self.output,
                "error_code": self.error_code,
                "error_message": self.error_message,
                "usage": self.usage,
                "provider": self.provider,
                "model": self.model,
                "latency_ms": self.latency_ms,
                "metadata": dict(self.metadata),
            }
        )


class CapabilityProvider(ABC):
    """Provider-independent interface. Implement for Yasin-AI or mocks."""

    name: str = "base"

    @abstractmethod
    def invoke(self, request: CapabilityRequest) -> CapabilityResponse:
        ...

    def supports(self, capability: CapabilityName) -> bool:
        return True


class MockCapabilityProvider(CapabilityProvider):
    """Deterministic mock for tests — no external credentials."""

    name = "mock"

    def __init__(self, *, fail: bool = False, delay: float = 0.0) -> None:
        self.fail = fail
        self.delay = delay
        self.calls: List[CapabilityRequest] = []

    def invoke(self, request: CapabilityRequest) -> CapabilityResponse:
        self.calls.append(request)
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            return CapabilityResponse(
                request_id=request.request_id,
                capability=request.capability.value,
                success=False,
                error_code=CapabilityErrorCode.PROVIDER_ERROR.value,
                error_message="mock failure",
                provider=self.name,
            )
        # Simple deterministic outputs
        out: Any
        cap = request.capability
        if cap == CapabilityName.EMBEDDING:
            out = [0.1, 0.2, 0.3]
        elif cap == CapabilityName.CLASSIFICATION:
            out = {"label": "positive", "score": 0.9}
        elif cap == CapabilityName.SUMMARIZATION:
            out = f"summary({request.input})"
        elif cap == CapabilityName.STRUCTURED_GENERATION:
            out = {"result": request.input, "structured": True}
        elif cap == CapabilityName.TOOL_SELECTION:
            out = {"tool": "noop", "args": {}}
        else:
            out = f"infer({request.input})"
        return CapabilityResponse(
            request_id=request.request_id,
            capability=cap.value,
            success=True,
            output=out,
            usage={"tokens": 10},
            provider=self.name,
            model="mock-model",
            latency_ms=1.0,
        )


class ConfigurableCapabilityProvider(MockCapabilityProvider):
    """Named provider/model wrapper. Still in-process; no network."""

    def __init__(
        self,
        *,
        provider: str = "yasin-ai",
        model: str = "default",
        fail: bool = False,
        delay: float = 0.0,
    ) -> None:
        super().__init__(fail=fail, delay=delay)
        self.name = provider
        self.model = model

    def invoke(self, request: CapabilityRequest) -> CapabilityResponse:
        resp = super().invoke(request)
        resp.provider = self.name
        resp.model = self.model
        return resp


class CapabilityClient:
    """
    Stable contract boundary used by the agent runtime.

    - Versioned requests
    - Timeout / retry
    - Error normalization
    - Observability via EventEmitter
    - Optional association with ExecutionRuntime
    - Loadout/capability gate when agent_id provided
    """

    def __init__(
        self,
        provider: Optional[CapabilityProvider] = None,
        *,
        runtime: Optional[ExecutionRuntime] = None,
        emitter: Optional[EventEmitter] = None,
        default_timeout: float = 30.0,
        max_retries: int = 1,
        allowed_capabilities: Optional[Sequence[str]] = None,
        memory_manager: Any = None,
    ) -> None:
        self._provider = provider or MockCapabilityProvider()
        self._runtime = runtime
        self._emitter = emitter or (runtime.events if runtime else EventEmitter())
        self._default_timeout = default_timeout
        self._max_retries = max(0, max_retries)
        self._allowed = set(allowed_capabilities) if allowed_capabilities else None
        self._memory = memory_manager
        self._lock = threading.Lock()
        self._call_count = 0

    @property
    def provider_name(self) -> str:
        return getattr(self._provider, "name", "unknown")

    def invoke(self, request: CapabilityRequest) -> CapabilityResponse:
        start = time.time()
        cap = (
            request.capability.value
            if isinstance(request.capability, CapabilityName)
            else str(request.capability)
        )
        if request.timeout_seconds is None or request.timeout_seconds <= 0:
            request.timeout_seconds = self._default_timeout

        if request.capability is None or cap == "":
            resp = CapabilityResponse(
                request_id=request.request_id,
                capability=cap or "unknown",
                success=False,
                error_code=CapabilityErrorCode.INVALID_REQUEST.value,
                error_message="capability is required",
                provider=self.provider_name,
            )
            self._emit(request, resp, start)
            return resp

        # Loadout gate: if a memory manager is bound and agent_id is set,
        # the capability must be listed on the active loadout.
        if self._memory is not None and request.agent_id:
            lo = self._memory.get_active_loadout(request.agent_id)
            if lo is not None and lo.capabilities and not lo.allows_capability(cap):
                resp = CapabilityResponse(
                    request_id=request.request_id,
                    capability=cap,
                    success=False,
                    error_code=CapabilityErrorCode.UNAUTHORIZED.value,
                    error_message=f"loadout denies capability: {cap}",
                    provider=self.provider_name,
                )
                self._emit(request, resp, start)
                return resp

        if self._allowed is not None:
            cap = (
                request.capability.value
                if isinstance(request.capability, CapabilityName)
                else str(request.capability)
            )
            if cap not in self._allowed:
                resp = CapabilityResponse(
                    request_id=request.request_id,
                    capability=cap,
                    success=False,
                    error_code=CapabilityErrorCode.UNAUTHORIZED.value,
                    error_message=f"capability not allowed: {cap}",
                    provider=self.provider_name,
                )
                self._emit(request, resp, start)
                return resp

        # Optional execution capability check
        if self._runtime and request.execution_id:
            try:
                self._runtime.check_capability(
                    request.execution_id, request.capability.value
                )
            except Exception as exc:
                resp = CapabilityResponse(
                    request_id=request.request_id,
                    capability=request.capability.value,
                    success=False,
                    error_code=CapabilityErrorCode.UNAUTHORIZED.value,
                    error_message=str(exc),
                    provider=self.provider_name,
                )
                self._emit(request, resp, start)
                return resp

        last: Optional[CapabilityResponse] = None
        attempts = 1 + self._max_retries
        for attempt in range(1, attempts + 1):
            try:
                # Soft timeout: provider should respect request.timeout_seconds;
                # we still measure and tag.
                resp = self._provider.invoke(request)
                elapsed = time.time() - start
                if resp.latency_ms is None:
                    resp.latency_ms = elapsed * 1000
                if elapsed > request.timeout_seconds:
                    resp = CapabilityResponse(
                        request_id=request.request_id,
                        capability=cap,
                        success=False,
                        error_code=CapabilityErrorCode.TIMEOUT.value,
                        error_message=f"capability timed out after {elapsed:.3f}s",
                        provider=self.provider_name,
                        latency_ms=elapsed * 1000,
                    )
                if resp.success or attempt >= attempts:
                    with self._lock:
                        self._call_count += 1
                    self._emit(request, resp, start)
                    return resp
                last = resp
            except Exception as exc:
                last = CapabilityResponse(
                    request_id=request.request_id,
                    capability=request.capability.value
                    if isinstance(request.capability, CapabilityName)
                    else str(request.capability),
                    success=False,
                    error_code=CapabilityErrorCode.PROVIDER_ERROR.value,
                    error_message=str(exc),
                    provider=self.provider_name,
                    latency_ms=(time.time() - start) * 1000,
                )
                if attempt >= attempts:
                    self._emit(request, last, start)
                    return last
        assert last is not None
        self._emit(request, last, start)
        return last

    def _emit(
        self,
        request: CapabilityRequest,
        response: CapabilityResponse,
        start: float,
    ) -> None:
        meta = {
            "capability": response.capability,
            "success": response.success,
            "request_id": request.request_id,
            "provider": response.provider,
            "latency_ms": response.latency_ms
            or (time.time() - start) * 1000,
        }
        if response.error_code:
            meta["error_code"] = response.error_code
        if response.usage:
            meta["usage"] = response.usage
        self._emitter.emit(
            "ai.capability",
            execution_id=request.execution_id or "",
            task_id=request.metadata.get("task_id", ""),
            session_id=request.metadata.get("session_id", ""),
            status="ok" if response.success else "error",
            metadata=meta,
            agent_id=request.agent_id,
        )

    @property
    def call_count(self) -> int:
        with self._lock:
            return self._call_count


__all__ = [
    "CapabilityName",
    "CapabilityErrorCode",
    "CapabilityRequest",
    "CapabilityResponse",
    "CapabilityProvider",
    "MockCapabilityProvider",
    "ConfigurableCapabilityProvider",
    "CapabilityClient",
]
