"""
hub_contract.py — Phase 5 explicit YasinHub ↔ Yasin-Agent integration contract.

Ownership (hard boundary):
  Hub: desired service state, start/stop/restart, PID supervision, operator API
  Agent: runtime, task/execution state, AI capability consumer, MCP tool boundary
  MCP: governed tool discovery/invocation
  AI: canonical model/provider capability
  Core: memory/runtime primitives via public SDK

This module does NOT implement a second control plane, registry, or PID authority.
"""

from __future__ import annotations

from typing import Final, FrozenSet

CONTRACT_VERSION: Final[str] = "1.0"
CONTRACT_NAME: Final[str] = "yasin-hub-agent"

# Execution lifecycle states Agent may report (truthful outcomes only)
EXECUTION_STATES: Final[FrozenSet[str]] = frozenset(
    {
        "queued",
        "running",
        "paused",
        "succeeded",
        "failed",
        "cancelled",
        "cancelling",
    }
)

TERMINAL_STATES: Final[FrozenSet[str]] = frozenset(
    {"succeeded", "failed", "cancelled"}
)

# HTTP paths Hub's HttpAgentRuntimeAdapter / HubAgentClient expect
HEALTH_PATH: Final[str] = "/v1/health"
READY_PATH: Final[str] = "/v1/ready"
EXECUTIONS_PATH: Final[str] = "/v1/executions"
EVENTS_PATH: Final[str] = "/v1/events"
FLEETS_PATH: Final[str] = "/v1/fleets"

HEADER_REQUEST_ID: Final[str] = "X-Request-Id"
HEADER_IDEMPOTENCY: Final[str] = "Idempotency-Key"
HEADER_CONTRACT: Final[str] = "X-Yasin-Contract-Version"

# Auth scheme
AUTH_SCHEME: Final[str] = "Bearer"


def is_terminal(status: str) -> bool:
    return str(status or "").lower() in TERMINAL_STATES


def contract_headers(request_id: str | None = None) -> dict:
    """Standard headers for Hub ↔ Agent HTTP calls."""
    headers = {HEADER_CONTRACT: CONTRACT_VERSION}
    if request_id:
        headers[HEADER_REQUEST_ID] = request_id
    return headers
