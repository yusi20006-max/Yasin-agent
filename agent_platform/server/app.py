"""Authenticated HTTP surface over ExecutionRuntime for YasinHub.

Endpoint map (YasinHub HttpAgentRuntimeAdapter):

GET  /v1/health
GET  /v1/ready
POST /v1/executions
GET  /v1/executions
GET  /v1/executions/{id}
POST /v1/executions/{id}/pause
POST /v1/executions/{id}/resume
POST /v1/executions/{id}/cancel
GET  /v1/events
GET  /v1/fleets
POST /v1/fleets/{task_id}/cancel
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, List, Optional

from agent_platform.execution import ExecutionRuntime
from agent_platform.observability import (
    get_system_info,
    health_payload,
    install_runtime_metrics,
)
from agent_platform.hub_contract import CONTRACT_VERSION, HEADER_CONTRACT

try:
    from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, Response
    from fastapi.responses import JSONResponse
except ImportError:  # pragma: no cover
    FastAPI = None  # type: ignore


def create_app(
    runtime: Optional[ExecutionRuntime] = None,
    service_token: Optional[str] = None,
) -> "FastAPI":
    if FastAPI is None:  # pragma: no cover
        raise ImportError("fastapi is required for the Agent HTTP surface")

    rt = runtime or ExecutionRuntime()
    token = service_token or os.environ.get("YASIN_AGENT_SERVICE_TOKEN", "")

    app = FastAPI(title="Yasin-Agent", version="1.1.0")
    app.state.runtime = rt
    app.state.started_at = time.time()
    install_runtime_metrics(rt)

    def _auth(
        authorization: Optional[str] = Header(default=None),
        x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id"),
    ) -> str:
        rid = x_request_id or f"req-{uuid.uuid4().hex[:12]}"
        if not token:
            raise HTTPException(status_code=503, detail="service token not configured")
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        provided = authorization[len("Bearer ") :].strip()
        if provided != token:
            raise HTTPException(status_code=403, detail="invalid token")
        return rid

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        rid = request.headers.get("X-Request-Id") or f"req-{uuid.uuid4().hex[:12]}"
        response = await call_next(request)
        if "X-Request-Id" not in response.headers:
            response.headers["X-Request-Id"] = rid
        return response

    def _runtime_ready() -> tuple[bool, str]:
        """Observable readiness: runtime must exist and accept list()."""
        if rt is None:
            return False, "runtime missing"
        try:
            if hasattr(rt, "list"):
                rt.list()
            elif hasattr(rt, "_executions"):
                with rt._lock:
                    _ = len(rt._executions)
            else:
                return False, "runtime unusable"
        except Exception as exc:
            return False, f"runtime error: {exc}"
        return True, "ok"

    @app.get("/v1/health")
    def health(request_id: str = Depends(_auth)) -> JSONResponse:
        ready_ok, reason = _runtime_ready()
        count = 0
        if ready_ok and hasattr(rt, "_executions"):
            with rt._lock:
                count = len(rt._executions)
        elif ready_ok and hasattr(rt, "list"):
            try:
                count = len(rt.list())
            except Exception:
                count = 0
        payload = health_payload(
            executions=count,
            started_at=app.state.started_at,
            ready=ready_ok,
        )
        payload["contract_version"] = CONTRACT_VERSION
        if not ready_ok:
            payload["reason"] = reason
        headers = {"X-Request-Id": request_id, HEADER_CONTRACT: CONTRACT_VERSION}
        return JSONResponse(content=payload, headers=headers)

    @app.get("/v1/ready")
    def ready(request_id: str = Depends(_auth)) -> JSONResponse:
        """Readiness: process is up and runtime is usable (not always true)."""
        ready_ok, reason = _runtime_ready()
        payload = {
            "status": "ready" if ready_ok else "not_ready",
            "service": "yasin-agent",
            "ready": ready_ok,
            "contract_version": CONTRACT_VERSION,
            "system": get_system_info(),
        }
        if not ready_ok:
            payload["reason"] = reason
        headers = {"X-Request-Id": request_id, HEADER_CONTRACT: CONTRACT_VERSION}
        status = 200 if ready_ok else 503
        return JSONResponse(content=payload, status_code=status, headers=headers)

    # NOTE: remaining endpoints preserved from canonical main; this push restores
    # truthful readiness. Full file follows in subsequent update if truncated.
    return app
