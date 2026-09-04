"""Phase 5 contract facade over the canonical Agent HTTP surface.

The canonical implementation is preserved in app_canonical.py. This module
adds only the Hub-Agent contract metadata and truthful readiness guard; it does
not introduce lifecycle/PID ownership.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from agent_platform.hub_contract import CONTRACT_VERSION, HEADER_CONTRACT
from agent_platform.observability import get_system_info
from . import app_canonical as _canonical

main = _canonical.main


def _runtime_ready(runtime: Any) -> tuple[bool, str]:
    if runtime is None:
        return False, "runtime missing"
    try:
        if hasattr(runtime, "list"):
            runtime.list()
        elif hasattr(runtime, "_executions"):
            with runtime._lock:
                len(runtime._executions)
        else:
            return False, "runtime unusable"
    except Exception as exc:
        return False, f"runtime error: {exc}"
    return True, "ok"


def create_app(
    *,
    runtime: Optional[Any] = None,
    service_token: Optional[str] = None,
    title: str = "Yasin-Agent Execution Runtime",
):
    app = _canonical.create_app(runtime=runtime, service_token=service_token)

    @app.middleware("http")
    async def phase5_contract_middleware(request, call_next):
        response = await call_next(request)
        response.headers[HEADER_CONTRACT] = CONTRACT_VERSION
        if request.url.path not in {"/v1/health", "/v1/ready"}:
            return response
        body = getattr(response, "body", None)
        if not body:
            return response
        try:
            payload = json.loads(body)
        except (TypeError, ValueError):
            return response
        payload["contract_version"] = CONTRACT_VERSION
        ready_ok, reason = _runtime_ready(getattr(app.state, "runtime", None))
        if request.url.path == "/v1/health":
            payload["ready"] = ready_ok
            if not ready_ok:
                payload["reason"] = reason
        else:
            payload["ready"] = ready_ok
            payload["status"] = "ready" if ready_ok else "not_ready"
            payload.setdefault("service", "yasin-agent")
            payload.setdefault("system", get_system_info())
            if not ready_ok:
                payload["reason"] = reason
        from fastapi.responses import JSONResponse
        headers = {k: v for k, v in response.headers.items() if k.lower() not in {"content-length", "content-type"}}
        headers[HEADER_CONTRACT] = CONTRACT_VERSION
        status_code = 503 if request.url.path == "/v1/ready" and not ready_ok else response.status_code
        return JSONResponse(content=payload, status_code=status_code, headers=headers)

    return app
