# Layered Memory & Agent Loadout (Issue #34)

## Layers

| Layer | Code | Role |
|-------|------|------|
| L0 Conversation | `L0` | Turn / session dialogue |
| L1 Atom | `L1` | Atomic facts / notes |
| L2 Scenario | `L2` | Episode / scenario bindings |
| L3 Core / Persona | `L3` | Stable identity |

Memory and Skill are separate asset types. Both are addressable in a loadout.

## Agent Loadout

A loadout is the explicit ACL for one agent:

- Memory bindings (`allow_read` / `allow_write`, optional session `scope`)
- Skill bindings
- Wiki / CodeGraph placeholders (`AssetType`)
- Runtime capabilities (`research`, `inference`, …)

Agents **do not** receive every memory automatically.

## ExecutionRuntime integration

```python
info = memory_manager.apply_to_execution(runtime, execution_id)
```

Intersects `execution.capabilities` with the agent's active loadout.
Does not grant extra capabilities.

## Persistence

`InMemoryMemoryStore` (default) or `JsonFileMemoryStore(root)`.
Provider-agnostic; no Yasin-AI coupling.

## Module map

| Module | Role |
|--------|------|
| `agent_platform/memory.py` | Assets, loadout, ACL, skills |
| `agent_platform/memory_context.py` | Legacy SDK session helpers |
| `tests/test_layered_memory.py` | Required coverage |
