# Multi-Agent Collaboration Harness

Issue #27 adds a lightweight orchestration boundary for running independent Yasin-Agent workers under one parent task.

## Boundary

`CollaborationHarness` owns worker registration, bounded concurrency, lifecycle coordination, cancellation signalling, and deterministic result aggregation. It does **not** grant tools or permissions. Yasin-MCP remains the authorization/governance boundary, and YasinHub is the future observer/control-plane consumer.

Each worker receives:

- a unique execution identity;
- a unique session identity;
- its own optional agent identity and workspace metadata;
- a copy of parent task context, so workers cannot mutate the parent's mapping or a sibling's mapping;
- an independent capability declaration.

No credentials or mutable authorization state are copied by the harness.

## Basic usage

```python
from agent_platform import CollaborationHarness


def worker(context, execution):
    return {"worker": context["worker_id"]}


harness = CollaborationHarness(max_concurrent_workers=4)
harness.register("research", worker, agent_id="research-agent")
harness.register("review", worker, agent_id="review-agent")

result = harness.run("task-123", context={"topic": "Yasin"})
```

`result.workers` is always ordered by `worker_id`, making parent aggregation deterministic.

## Events

The harness uses the Issue #26 `ExecutionRuntime` event stream. Events carry `task_id`, `execution_id`, `session_id`, `agent_id`, and workspace identity where available. A `worker.registered` event adds the worker-level correlation identifier. Event metadata is passed through the existing secret-redaction boundary.

YasinHub can later subscribe to `harness.events` without embedding UI or transport code in Yasin-Agent.

## Failure and cancellation

A worker exception becomes a `WorkerResult(status="failed")` and does not poison sibling workers. A parent with one or more failed workers is reported as `completed_with_failures`.

Cancellation is cooperative. `harness.cancel(task_id)` signals all active workers and cancels their execution records. A worker that is already inside an arbitrary Python call cannot be forcibly killed by this thread-based runtime; worker code should check `context["cancellation_requested"]()` at safe boundaries.

## Security constraints

This layer deliberately does not add shell execution, unrestricted filesystem access, credential sharing, privilege escalation, or UI integrations. Capability declarations are descriptive/isolating metadata; actual tool authorization remains independently enforced by Yasin-MCP.
