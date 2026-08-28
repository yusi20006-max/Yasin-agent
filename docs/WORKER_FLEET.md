# Worker Fleet — Issue #28

`WorkerFleet` is the orchestration layer for bounded parallel Yasin-Agent workers. It does not provide UI, shell execution, computer-use, credentials, or tool authorization.

## Boundaries

- **Yasin-Agent:** worker planning, concurrency, lifecycle and aggregation.
- **Yasin-Core:** reusable SDK/runtime primitives.
- **Yasin-MCP:** authorization, governance, approval and audit of tools.
- **YasinHub:** future observation/control-plane consumer.

A worker receives an explicit role, objective, workspace, capabilities and metadata. Worker sessions/executions are independent. Capabilities are never inherited from sibling workers.

## API contract

```python
from agent_platform import FleetWorkerPlan, WorkerFleet

fleet = WorkerFleet(max_workers=8, max_concurrent_workers=4)
fleet.register(FleetWorkerPlan(
    worker_id="research-1",
    role="researcher",
    objective="collect evidence",
    runner=runner,
    capabilities=("search",),
))
result = fleet.run("task-1")
status = fleet.status("task-1")
```

`FleetStatus.as_dict()` is intentionally JSON-shaped for a future YasinHub API. Workers are sorted by `worker_id`, making snapshots and aggregation deterministic.

## States and events

Worker lifecycle is represented through the Issue #26 execution boundary (`queued`, `running`, `succeeded`, `failed`, `cancelled`). Fleet-level status additionally reports `cancelling` while cancellation is propagating and the terminal aggregation status afterwards.

Relevant event types are:

- `worker.registered`
- `worker.progress`
- `execution.*` events from the execution boundary
- `fleet.completed`

Events contain task/execution/session correlation and workspace identity where an execution exists. Secret-looking metadata is redacted by the execution event emitter.

## Failure and cancellation

A worker exception is isolated and becomes `failed`; sibling workers continue. The parent result becomes `completed_with_failures` when any worker fails. Parent cancellation is propagated to all active executions and is cooperative, matching Issue #26 semantics.

Concurrency is bounded by `max_concurrent_workers`, and the total registered/selected fleet size is bounded by `max_workers`.

## Non-goals

Issue #28 does not add PWA/Telegram/Discord UI, distributed execution, unrestricted filesystem/shell access, credential sharing, privilege escalation, or changes to Yasin-MCP governance.
