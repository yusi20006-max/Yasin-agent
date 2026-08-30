# Production Observability (Issue #42)

## Correlation

`correlation_context(request_id=, execution_id=, job_id=, task_id=, session_id=, agent_id=)`

## Metrics (in-process)

Counters: executions created/running/succeeded/failed/cancelled/paused,
scheduler_failures, http_requests/errors, ai_capability_failures, research_failures,
total_execution_duration_seconds.

Hook: `install_runtime_metrics(runtime)` (auto-installed by HTTP server).

## Endpoints

| Path | Purpose |
|------|---------|
| `GET /v1/health` | Health + metrics snapshot |
| `GET /v1/ready` | Readiness |
| `GET /v1/metrics` | Metrics only |
| `GET /v1/executions/{id}/diagnostics` | Secret-free execution diagnostics |

## Diagnostics

`execution_diagnostics(record)` returns status, duration, capability set,
checkpoint keys, error — never secret values.

## Logging

`structured_log(level, message, **fields)` + `safe_log_extra` redacts tokens/keys.
