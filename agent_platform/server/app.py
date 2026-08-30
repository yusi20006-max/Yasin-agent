"""Authenticated HTTP surface over ExecutionRuntime for YasinHub.

Endpoint map (YasinHub HttpAgentRuntimeAdapter):

GET  /v1/health
GET  /v1/ready
POST /v1/executions
GET  /v1/executions
GET  /v1/executions/{execution_id}
GET  /v1/executions/{execution_id}/events
GET  /v1/events
POST /v1/executions/{execution_id}/pause
POST /v1/executions/{execution_id}/resume
POST /v1/executions/{execution_id}/cancel
GET  /v1/fleets
GET  /v1/fleets/{task_id}
POST /v1/fleets/{task_id}/cancel

Auth: Authorization: Bearer <service_token>
Request identity: X-Request-Id (echoed on responses)
"""

from __future__ import annotations

import os
import secrets
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from agent_platform.execution import ExecutionRuntime, ExecutionState, redact_secrets
from agent_platform.state_machine import InvalidTransitionError
from agent_platform.observability import (
    execution_diagnostics,
    get_metrics,
    health_payload,
    install_runtime_metrics,
)

try:
    from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, Response
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover - exercised by core-import test
    raise ImportError(
        "HTTP server dependencies are not installed. "
        "Install with: pip install 'yasin-agent[server]'"
    ) from exc


class ControlBody(BaseModel):
    request_id: Optional[str] = None
    actor: Optional[str] = None
    source: Optional[str] = None


def _require_server_deps() -> None:
    import fastapi  # noqa: F401
    import uvicorn  # noqa: F401


def create_app(
    *,
    runtime: Optional[ExecutionRuntime] = None,
    service_token: Optional[str] = None,
    title: str = "Yasin-Agent Execution Runtime",
) -> FastAPI:
    """Build the FastAPI app bound to an ExecutionRuntime instance."""
    rt = runtime or ExecutionRuntime()
    token = (service_token if service_token is not None else os.environ.get("YASIN_AGENT_SERVICE_TOKEN", "")).strip()
    if not token:
        token = ""

    app = FastAPI(title=title, version="1.0.0")
    app.state.runtime = rt
    app.state.service_token = token
    app.state.started_at = time.time()
    app.state.idempotency: Dict[Tuple[str, str, str], Tuple[int, Any]] = {}
    app.state.idem_lock = threading.Lock()
    install_runtime_metrics(rt)
    metrics = get_metrics()

    def _auth(
        authorization: Optional[str] = Header(default=None),
        x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id"),
    ) -> str:
        expected = app.state.service_token
        if not expected:
            raise HTTPException(status_code=503, detail="service token not configured")
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing or invalid authorization")
        provided = authorization.split(" ", 1)[1].strip()
        if not provided or not secrets.compare_digest(provided, expected):
            raise HTTPException(status_code=401, detail="invalid service token")
        return x_request_id or f"req-{uuid.uuid4().hex[:16]}"

    def _record_dict(record) -> Dict[str, Any]:
        return record.as_dict()

    def _event_dict(event) -> Dict[str, Any]:
        return event.as_dict()

    def _get_or_recover(execution_id: str):
        """In-memory first; then durable store recovery (Hub restart path)."""
        rec = rt.get(execution_id)
        if rec is not None:
            return rec
        try:
            return rt.recover(execution_id)
        except (KeyError, ValueError):
            return None

    def _fleet_from_task(task_id: str) -> Optional[Dict[str, Any]]:
        items = rt.list_executions(task_id=task_id)
        if not items:
            return None
        workers = []
        statuses = []
        for rec in items:
            statuses.append(rec.status.value)
            workers.append(
                {
                    "worker_id": rec.metadata.get("worker_id") or rec.execution_id,
                    "role": rec.metadata.get("role") or "agent",
                    "objective": rec.metadata.get("objective") or "",
                    "status": rec.status.value,
                    "execution_id": rec.execution_id,
                    "session_id": rec.session_id,
                    "progress": redact_secrets(rec.metadata.get("progress")),
                    "result": redact_secrets(rec.result),
                    "error": rec.error,
                    "cancellation_state": "requested" if rec.cancel_requested else None,
                    "agent_id": rec.agent_id,
                }
            )
        if all(s in {"succeeded", "failed", "cancelled"} for s in statuses):
            if any(s == "failed" for s in statuses):
                fleet_status = "failed"
            elif any(s == "cancelled" for s in statuses):
                fleet_status = "cancelled"
            else:
                fleet_status = "succeeded"
        elif any(s == "running" for s in statuses):
            fleet_status = "running"
        elif any(s == "paused" for s in statuses):
            fleet_status = "paused"
        else:
            fleet_status = "queued"
        return {"task_id": task_id, "status": fleet_status, "workers": workers}

    def _control(
        action: str,
        execution_id: str,
        request_id: str,
        idempotency_key: Optional[str],
        body: Optional[ControlBody],
    ) -> JSONResponse:
        path = f"/v1/executions/{execution_id}/{action}"
        if idempotency_key:
            cache_key = ("POST", path, idempotency_key)
            with app.state.idem_lock:
                if cache_key in app.state.idempotency:
                    status, payload = app.state.idempotency[cache_key]
                    return JSONResponse(status_code=status, content=payload, headers={"X-Request-Id": request_id})

        rec = _get_or_recover(execution_id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"execution not found: {execution_id}")
        try:
            if action == "pause":
                rec = rt.pause(execution_id)
            elif action == "resume":
                rec = rt.resume(execution_id)
            elif action == "cancel":
                rec = rt.cancel(execution_id)
            else:
                raise HTTPException(status_code=400, detail=f"unknown action: {action}")
        except InvalidTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        payload = _record_dict(rec)
        if idempotency_key:
            with app.state.idem_lock:
                app.state.idempotency[("POST", path, idempotency_key)] = (200, payload)
        return JSONResponse(content=payload, headers={"X-Request-Id": request_id})

    @app.middleware("http")
    async def _attach_request_id(request: Request, call_next: Callable):
        metrics.inc("http_requests")
        response = await call_next(request)
        if response.status_code >= 400:
            metrics.inc("http_errors")
        rid = request.headers.get("X-Request-Id")
        if rid and "X-Request-Id" not in response.headers:
            response.headers["X-Request-Id"] = rid
        return response

    @app.get("/v1/health")
    def health(request_id: str = Depends(_auth)) -> JSONResponse:
        with rt._lock:
            count = len(rt._executions)
        payload = health_payload(
            executions=count,
            started_at=app.state.started_at,
            ready=True,
        )
        return JSONResponse(content=payload, headers={"X-Request-Id": request_id})

    @app.get("/v1/ready")
    def ready(request_id: str = Depends(_auth)) -> JSONResponse:
        """Readiness: process is up and runtime is usable."""
        payload = {
            "status": "ready",
            "service": "yasin-agent",
            "ready": True,
        }
        return JSONResponse(content=payload, headers={"X-Request-Id": request_id})

    @app.get("/v1/metrics")
    def metrics_endpoint(request_id: str = Depends(_auth)) -> JSONResponse:
        return JSONResponse(
            content={"metrics": metrics.snapshot()},
            headers={"X-Request-Id": request_id},
        )

    @app.get("/v1/executions/{execution_id}/diagnostics")
    def execution_diagnostics_endpoint(
        execution_id: str, request_id: str = Depends(_auth)
    ) -> JSONResponse:
        rec = _get_or_recover(execution_id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"execution not found: {execution_id}")
        return JSONResponse(
            content=execution_diagnostics(rec),
            headers={"X-Request-Id": request_id},
        )

    @app.post("/v1/executions")
    def create_execution(
        body: Dict[str, Any] = Body(default_factory=dict),
        request_id: str = Depends(_auth),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        """Create an execution via ExecutionRuntime.create()."""
        path = "/v1/executions"
        if idempotency_key:
            cache_key = ("POST", path, idempotency_key)
            with app.state.idem_lock:
                if cache_key in app.state.idempotency:
                    status, payload = app.state.idempotency[cache_key]
                    return JSONResponse(
                        status_code=status,
                        content=payload,
                        headers={"X-Request-Id": request_id},
                    )
        task_id = body.get("task_id")
        if not task_id or not isinstance(task_id, str):
            raise HTTPException(status_code=400, detail="task_id is required")
        session_id = body.get("session_id")
        agent_id = body.get("agent_id")
        capabilities = body.get("capabilities")
        metadata = body.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        execution_id = body.get("execution_id")
        start = bool(body.get("start", False))
        try:
            rec = rt.create(
                task_id=task_id,
                session_id=session_id,
                agent_id=agent_id,
                capabilities=capabilities,
                metadata=metadata,
                execution_id=execution_id,
            )
            if start:
                rec = rt.start(rec.execution_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        payload = _record_dict(rec)
        if idempotency_key:
            with app.state.idem_lock:
                app.state.idempotency[("POST", path, idempotency_key)] = (201, payload)
        return JSONResponse(
            status_code=201,
            content=payload,
            headers={"X-Request-Id": request_id},
        )

    @app.get("/v1/executions")
    def list_executions(
        request_id: str = Depends(_auth),
        task_id: Optional[str] = Query(default=None),
        session_id: Optional[str] = Query(default=None),
        status: Optional[str] = Query(default=None),
    ) -> JSONResponse:
        items = rt.list_executions(task_id=task_id, session_id=session_id)
        if status:
            items = [e for e in items if e.status.value == status]
        payload = {"items": [_record_dict(e) for e in items]}
        return JSONResponse(content=payload, headers={"X-Request-Id": request_id})

    @app.get("/v1/executions/{execution_id}")
    def get_execution(execution_id: str, request_id: str = Depends(_auth)) -> JSONResponse:
        rec = _get_or_recover(execution_id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"execution not found: {execution_id}")
        return JSONResponse(content=_record_dict(rec), headers={"X-Request-Id": request_id})

    @app.get("/v1/executions/{execution_id}/events")
    def list_execution_events(
        execution_id: str,
        request_id: str = Depends(_auth),
        event_type: Optional[str] = Query(default=None),
        limit: Optional[int] = Query(default=None),
    ) -> JSONResponse:
        if _get_or_recover(execution_id) is None:
            raise HTTPException(status_code=404, detail=f"execution not found: {execution_id}")
        events = rt.events.history(execution_id=execution_id)
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if limit is not None and limit >= 0:
            events = events[-limit:]
        payload = {"items": [_event_dict(e) for e in events]}
        return JSONResponse(content=payload, headers={"X-Request-Id": request_id})

    @app.get("/v1/events")
    def list_events(
        request_id: str = Depends(_auth),
        execution_id: Optional[str] = Query(default=None),
        task_id: Optional[str] = Query(default=None),
        session_id: Optional[str] = Query(default=None),
        worker_id: Optional[str] = Query(default=None),
        event_type: Optional[str] = Query(default=None),
        limit: Optional[int] = Query(default=None),
    ) -> JSONResponse:
        events = rt.events.history(execution_id=execution_id, task_id=task_id)
        if session_id:
            events = [e for e in events if e.session_id == session_id]
        if worker_id:
            events = [e for e in events if (e.metadata or {}).get("worker_id") == worker_id]
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if limit is not None and limit >= 0:
            events = events[-limit:]
        payload = {"items": [_event_dict(e) for e in events]}
        return JSONResponse(content=payload, headers={"X-Request-Id": request_id})

    @app.post("/v1/executions/{execution_id}/pause")
    def pause_execution(
        execution_id: str,
        body: ControlBody = ControlBody(),
        request_id: str = Depends(_auth),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        rid = body.request_id or request_id
        return _control("pause", execution_id, rid, idempotency_key, body)

    @app.post("/v1/executions/{execution_id}/resume")
    def resume_execution(
        execution_id: str,
        body: ControlBody = ControlBody(),
        request_id: str = Depends(_auth),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        rid = body.request_id or request_id
        return _control("resume", execution_id, rid, idempotency_key, body)

    @app.post("/v1/executions/{execution_id}/cancel")
    def cancel_execution(
        execution_id: str,
        body: ControlBody = ControlBody(),
        request_id: str = Depends(_auth),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        rid = body.request_id or request_id
        return _control("cancel", execution_id, rid, idempotency_key, body)

    @app.get("/v1/fleets")
    def list_fleets(request_id: str = Depends(_auth)) -> JSONResponse:
        with rt._lock:
            task_ids = sorted({e.task_id for e in rt._executions.values()})
        fleets = []
        for tid in task_ids:
            fleet = _fleet_from_task(tid)
            if fleet:
                fleets.append(fleet)
        return JSONResponse(content={"items": fleets}, headers={"X-Request-Id": request_id})

    @app.get("/v1/fleets/{task_id}")
    def get_fleet(task_id: str, request_id: str = Depends(_auth)) -> JSONResponse:
        fleet = _fleet_from_task(task_id)
        if fleet is None:
            raise HTTPException(status_code=404, detail=f"fleet not found: {task_id}")
        return JSONResponse(content=fleet, headers={"X-Request-Id": request_id})

    @app.post("/v1/fleets/{task_id}/cancel")
    def cancel_fleet(
        task_id: str,
        body: ControlBody = ControlBody(),
        request_id: str = Depends(_auth),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        path = f"/v1/fleets/{task_id}/cancel"
        if idempotency_key:
            cache_key = ("POST", path, idempotency_key)
            with app.state.idem_lock:
                if cache_key in app.state.idempotency:
                    status, payload = app.state.idempotency[cache_key]
                    return JSONResponse(status_code=status, content=payload, headers={"X-Request-Id": request_id})
        items = rt.list_executions(task_id=task_id)
        if not items:
            raise HTTPException(status_code=404, detail=f"fleet not found: {task_id}")
        for rec in items:
            if not rec.is_terminal():
                try:
                    rt.cancel(rec.execution_id)
                except InvalidTransitionError:
                    pass
        fleet = _fleet_from_task(task_id)
        payload = fleet or {"task_id": task_id, "status": "cancelled", "workers": []}
        if idempotency_key:
            with app.state.idem_lock:
                app.state.idempotency[("POST", path, idempotency_key)] = (200, payload)
        return JSONResponse(content=payload, headers={"X-Request-Id": request_id})

    return app


def run_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    service_token: Optional[str] = None,
    runtime: Optional[ExecutionRuntime] = None,
) -> None:
    """Start uvicorn serving the HTTP adapter."""
    _require_server_deps()
    import uvicorn

    app = create_app(runtime=runtime, service_token=service_token)
    uvicorn.run(app, host=host, port=port, log_level="info")


def main() -> None:
    host = os.environ.get("YASIN_AGENT_HOST", "127.0.0.1")
    port = int(os.environ.get("YASIN_AGENT_PORT", "8080"))
    token = os.environ.get("YASIN_AGENT_SERVICE_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "YASIN_AGENT_SERVICE_TOKEN is required to start the HTTP runtime adapter"
        )
    run_server(host=host, port=port, service_token=token)


if __name__ == "__main__":
    main()
