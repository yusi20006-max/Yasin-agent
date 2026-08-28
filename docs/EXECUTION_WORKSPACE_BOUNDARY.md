# Observable Execution Workspace Boundary (Issue #26)

## Architecture principle

```
YasinHub          — future observation / control-plane consumer
    ↓
Yasin-Agent       — execution lifecycle, workspace boundary, events, orchestration
    ↓
Yasin-MCP         — tool governance, authentication, authorization, approval, audit
```

**Yasin-Agent owns execution lifecycle and orchestration.**
**Yasin-MCP remains the tool governance and authorization boundary.**
**YasinHub is the future observation/control-plane consumer.**

## 1. What is an execution?

An **execution** is one observable unit of agent work (`ExecutionRecord` / `ExecutionRuntime`).

| Field | Meaning |
|-------|---------|
| `execution_id` | Stable unique ID |
| `task_id` / `session_id` | Correlation |
| `workspace` | Explicit workspace identity + scope |
| `capabilities` | Allow-list (deny-by-default) |
| `status` | Lifecycle state |
| timestamps / error / result / metadata | Audit (secret-redacted on serialize) |

## 2. Lifecycle

`queued` → `running` ↔ `paused` → `succeeded` | `failed` | `cancelled`

Terminal states accept no further transitions (`InvalidTransitionError`).

## 3. Workspace boundary

`WorkspaceBound` is metadata only (`workspace_id`, optional `path`, `scope`).
**No filesystem or shell APIs.**

## 4. Capability boundary

Allow-list; empty list denies all. `check_capability` emits `capability.denied`.

## 5. Events

`ExecutionEvent`: event_id, event_type, timestamp, execution_id, task_id, session_id, status, metadata.

## 6–7. Cancel / pause

Cancel deterministic from non-terminal. Pause is **cooperative** (`metadata.cooperative=true`).

## 8. Secret redaction

Keys/patterns for token, api_key, password, bearer, sk-… redacted in events and `as_dict()`.

## 9. YasinHub

Consume via `list_executions`, `as_dict()`, `EventEmitter.history`.

## 10. Out of scope

#27, #28, shell, unrestricted FS, Telegram, Discord, PWA, MCP changes.

## Module

`agent_platform/execution.py`
