# HTTP Execution Runtime adapter (Issue #38)

Minimal authenticated HTTP surface over the existing `ExecutionRuntime` so
YasinHub can connect with `HttpAgentRuntimeAdapter`.

## Architecture

```text
YasinHub
  → HttpAgentRuntimeAdapter
  → HTTP /v1/*
  → agent_platform.server
  → ExecutionRuntime
```

No second execution engine. Lifecycle and events remain owned by
`ExecutionRuntime`.

## Install (optional)

```sh
pip install 'yasin-agent[server]'
# or from a checkout:
pip install -e '.[server]'
```

Core `yasin-agent` does **not** require FastAPI/uvicorn.

## Start

```sh
export YASIN_AGENT_SERVICE_TOKEN="replace-with-shared-secret"
export YASIN_AGENT_HOST=127.0.0.1
export YASIN_AGENT_PORT=8080
python -m agent_platform.server
# or: yasin-agent-server
```

## YasinHub configuration

```sh
export YASINHUB_AGENT_BASE_URL="http://127.0.0.1:8080"
export YASINHUB_AGENT_SERVICE_TOKEN="replace-with-shared-secret"
```

`YASINHUB_AGENT_SERVICE_TOKEN` and `YASIN_AGENT_SERVICE_TOKEN` must match.

## Endpoint map (Hub contract)

| Hub method | HTTP |
| --- | --- |
| health | `GET /v1/health` |
| list_executions | `GET /v1/executions?task_id&session_id&status` |
| get_execution | `GET /v1/executions/{id}` |
| list_events | `GET /v1/events` or `GET /v1/executions/{id}/events` |
| list_fleets | `GET /v1/fleets` |
| get_fleet | `GET /v1/fleets/{task_id}` |
| pause | `POST /v1/executions/{id}/pause` |
| resume | `POST /v1/executions/{id}/resume` |
| cancel | `POST /v1/executions/{id}/cancel` |
| cancel_fleet | `POST /v1/fleets/{task_id}/cancel` |

## Authentication

All `/v1/*` endpoints require:

```http
Authorization: Bearer <service_token>
```

Missing or invalid tokens return `401`.

## Request identity

Clients may send `X-Request-Id`. The adapter echoes it on responses.
Control bodies may also include `request_id`, `actor`, and `source`.

Control posts accept `Idempotency-Key` for safe retries.

## Lifecycle

Pause/resume/cancel map directly to `ExecutionRuntime` transitions.
Invalid transitions return `409`. Missing executions return `404`.

Fleet views are derived by grouping executions that share `task_id`.
Fleet cancel cancels every non-terminal execution in that group.

## Security

- Tokens are never logged by this adapter.
- Execution payloads use existing `redact_secrets`.
- No shell, unrestricted filesystem, or remote code APIs are exposed.
