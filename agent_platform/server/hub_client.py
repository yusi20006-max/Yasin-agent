"""
hub_client.py — minimal Hub-side HTTP client for Yasin-Agent (Issue #41).

Handles request IDs, bearer auth, idempotency keys, and bounded retries on
transient connection failures. Does not invent endpoints beyond the Agent API.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional


class HubAgentError(Exception):
    def __init__(self, status_code: int, detail: Any, request_id: Optional[str] = None) -> None:
        self.status_code = status_code
        self.detail = detail
        self.request_id = request_id
        super().__init__(f"HTTP {status_code}: {detail}")


class HubAgentClient:
    """Thin client matching YasinHub HttpAgentRuntimeAdapter needs."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        http: Any = None,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.05,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._http = http
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = retry_backoff_seconds
        self.timeout_seconds = timeout_seconds

    def _session(self) -> Any:
        if self._http is not None:
            return self._http
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise ImportError("httpx required for HubAgentClient") from exc
        return httpx.Client(timeout=self.timeout_seconds)

    def _headers(
        self,
        *,
        request_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.token}",
            "X-Request-Id": request_id or f"hub-{uuid.uuid4().hex[:12]}",
        }
        if idempotency_key:
            h["Idempotency-Key"] = idempotency_key
        return h

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = self._headers(request_id=request_id, idempotency_key=idempotency_key)
        session = self._session()
        last_exc: Optional[Exception] = None
        attempts = 1 + self.max_retries
        for attempt in range(1, attempts + 1):
            try:
                if hasattr(session, "request"):
                    resp = session.request(method, url, headers=headers, json=json)
                else:  # pragma: no cover
                    raise RuntimeError("http client missing request()")
                if resp.status_code >= 500 and attempt < attempts:
                    time.sleep(self.retry_backoff_seconds * attempt)
                    continue
                if resp.status_code >= 400:
                    try:
                        detail = resp.json()
                    except Exception:
                        detail = getattr(resp, "text", str(resp.status_code))
                    raise HubAgentError(
                        resp.status_code,
                        detail,
                        request_id=resp.headers.get("X-Request-Id"),
                    )
                return resp.json()
            except HubAgentError:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt >= attempts:
                    break
                time.sleep(self.retry_backoff_seconds * attempt)
        raise HubAgentError(503, f"transport failure: {last_exc}")

    def health(self) -> Dict[str, Any]:
        return self._request("GET", "/v1/health")

    def ready(self) -> Dict[str, Any]:
        return self._request("GET", "/v1/ready")

    def create_execution(
        self,
        task_id: str,
        *,
        start: bool = False,
        agent_id: Optional[str] = None,
        capabilities: Optional[list] = None,
        metadata: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"task_id": task_id, "start": start}
        if agent_id is not None:
            body["agent_id"] = agent_id
        if capabilities is not None:
            body["capabilities"] = capabilities
        if metadata is not None:
            body["metadata"] = metadata
        if session_id is not None:
            body["session_id"] = session_id
        if execution_id is not None:
            body["execution_id"] = execution_id
        return self._request(
            "POST",
            "/v1/executions",
            json=body,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )

    def get_execution(self, execution_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/v1/executions/{execution_id}")

    def list_executions(self, **params: Any) -> Dict[str, Any]:
        # query params left to caller via path if needed; keep simple
        return self._request("GET", "/v1/executions")

    def list_events(self, execution_id: Optional[str] = None) -> Dict[str, Any]:
        if execution_id:
            return self._request("GET", f"/v1/executions/{execution_id}/events")
        return self._request("GET", "/v1/events")

    def pause(self, execution_id: str, *, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/executions/{execution_id}/pause",
            json={},
            idempotency_key=idempotency_key,
        )

    def resume(self, execution_id: str, *, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/executions/{execution_id}/resume",
            json={},
            idempotency_key=idempotency_key,
        )

    def cancel(self, execution_id: str, *, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/executions/{execution_id}/cancel",
            json={},
            idempotency_key=idempotency_key,
        )

    def list_fleets(self) -> Dict[str, Any]:
        return self._request("GET", "/v1/fleets")

    def cancel_fleet(self, task_id: str) -> Dict[str, Any]:
        return self._request("POST", f"/v1/fleets/{task_id}/cancel", json={})


__all__ = ["HubAgentClient", "HubAgentError"]
