# YasinHub ↔ Yasin-Agent E2E Orchestration (Issue #41)

## Endpoint map

| Method | Path | Role |
|--------|------|------|
| GET | `/v1/health` | Liveness |
| GET | `/v1/ready` | Readiness |
| POST | `/v1/executions` | Create (maps to `ExecutionRuntime.create`) |
| GET | `/v1/executions` | List |
| GET | `/v1/executions/{id}` | Get (+ durable recover) |
| GET | `/v1/executions/{id}/events` | Execution events |
| GET | `/v1/events` | Global events |
| POST | `/v1/executions/{id}/pause\|resume\|cancel` | Lifecycle |
| GET/POST | `/v1/fleets...` | Fleet ops |

Auth: `Authorization: Bearer <token>`  
Correlation: `X-Request-Id`  
Idempotency: `Idempotency-Key` on mutating POSTs

## Create body

```json
{
  "task_id": "required",
  "session_id": "optional",
  "agent_id": "optional",
  "capabilities": ["read"],
  "metadata": {},
  "execution_id": "optional-client-supplied",
  "start": true
}
```

## Error codes

| Code | Meaning |
|------|---------|
| 401 | Bad/missing token |
| 404 | Unknown execution/fleet |
| 409 | Duplicate id or invalid lifecycle transition |
| 400 | Missing `task_id` |

## Restart recovery

With `JsonFileExecutionStore` (or any `ExecutionStore`), a new Agent process
recovers non-terminal executions on GET/pause/resume/cancel via
`ExecutionRuntime.recover`.

## Hub client

```python
from agent_platform.server.hub_client import HubAgentClient
client = HubAgentClient(base_url="http://127.0.0.1:8080", token="secret")
client.health()
rec = client.create_execution("task-1", start=True, capabilities=["read"])
client.pause(rec["execution_id"])
```

Retries transient connection / 5xx failures with bounded backoff.
