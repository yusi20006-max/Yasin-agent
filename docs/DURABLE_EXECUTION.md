# Durable Execution, Recovery & Resume (Issue #32)

## Goal

Allow long-running agent executions to survive process restart and be
resumed deterministically without rewriting the Issue #26 lifecycle.

## Architecture

```text
ExecutionRuntime  (authoritative in-process lifecycle)
        |
        +-- EventEmitter          (in-process observability)
        |
        +-- ExecutionStore?       (optional, provider-agnostic)
                 +-- InMemoryExecutionStore   (default / tests)
                 +-- JsonFileExecutionStore   (local durable)
```

- **Default**: no store -> pure in-memory (backward compatible with #26).
- **With store**: every successful lifecycle mutation writes a secret-safe
  snapshot via `ExecutionRecord.as_dict()`.
- Recovery loads snapshots into a new `ExecutionRuntime` instance.
- Resume is explicit: terminal states cannot be resumed.

## Checkpoint

`save_checkpoint(execution_id, data, merge=True)` attaches a redacted
payload to a **non-terminal** execution. Callers decide the schema
(step index, cursor, partial results). The runtime does not interpret it.

## Recovery semantics

| Method | Behaviour |
|--------|-----------|
| `recover(id)` | Load from store into memory if missing; idempotent |
| `recover_all()` | Load every stored id not already in memory |
| `resume(id)` | `queued`/`paused` -> `running`; terminal -> `InvalidTransitionError` |
| `list_recoverable()` | Non-terminal executions currently in memory |

Duplicate recovery does not create a second record. Event sequence numbers
continue to increase on the live emitter after recovery (recovery itself
emits a `state_changed` with `metadata.recovered=true`).

## Safety

- Snapshots use `redact_secrets` — tokens/keys never land on disk.
- Persistence failure is logged and does **not** break the in-memory
  lifecycle (execution authority stays in process).
- No privilege escalation: recovered records keep the original
  `capabilities` and `workspace` metadata only.
- Store is replaceable; do not hard-code a database driver here.

## Out of scope

- Scheduler / cron (#33)
- Layered memory / loadout (#34)
- Yasin-AI provider logic (#35)
- External research tools (#36)
- Shell / unrestricted filesystem / browser automation

## Module map

| Module | Role |
|--------|------|
| `agent_platform/execution.py` | Lifecycle + recover/resume/checkpoint |
| `agent_platform/persistence.py` | `ExecutionStore` + in-memory / JSON backends |
| `tests/test_durable_execution.py` | Required coverage |
