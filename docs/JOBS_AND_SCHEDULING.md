# Persistent Jobs & Scheduling (Issue #33)

## Goal

Provide a durable job/scheduling layer on top of `ExecutionRuntime` so that
work definitions survive process restart, support delayed/recurring runs,
bounded retries, and never create duplicate executions after recovery.

## Architecture

```text
JobScheduler
    |
    +-- JobStore?          (optional; InMemory / JsonFile)
    |
    +-- ExecutionRuntime   (authoritative execution lifecycle)
            |
            +-- EventEmitter
            +-- ExecutionStore?
```

- **Job** = durable definition of work (task, schedule, retry, metadata).
- **Execution** = one concrete run produced by the runtime.
- Scheduler creates executions via `ExecutionRuntime.create()` + `start()`.
- Outcomes are mapped back with `on_execution_terminal()`.

## Job states

| State       | Meaning                                      |
|-------------|----------------------------------------------|
| queued      | Created, not yet due                         |
| scheduled   | Waiting for `run_at` / retry / recurrence    |
| running     | Has an active non-terminal execution         |
| paused      | Cooperative pause                            |
| succeeded   | Terminal success (non-recurring)             |
| failed      | Terminal failure (retries exhausted)         |
| cancelled   | Terminal cancel                              |

## ScheduleSpec

- `immediate=True` — run as soon as possible (default).
- `run_at=<unix ts>` — one-shot delayed/scheduled.
- `interval_seconds=N` — after success, re-schedule after N seconds.

## RetryPolicy

- `max_attempts` (default 1) — bounded.
- `backoff_seconds` + exponential growth, capped by `max_backoff_seconds`.

## Recovery

- `recover(job_id)` / `recover_all()` load snapshots into a new scheduler.
- Linked executions are recovered via `ExecutionRuntime.recover`.
- `tick()` is idempotent: if an execution is already attached and non-terminal,
  no second execution is created.

## Events

Job lifecycle emits `job.*` events on the shared `EventEmitter` (same bus as
executions). Metadata always includes `job_id` and `attempt`.

## Out of scope

- Distributed multi-node leader election
- Full cron expression parser
- Shell / unrestricted network from the scheduler itself

## Module map

| Module | Role |
|--------|------|
| `agent_platform/jobs.py` | JobRecord, JobScheduler, stores |
| `tests/test_jobs.py` | Required coverage |
