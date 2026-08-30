# Yasin-AI Capability Boundary (Issue #35)

Yasin-Agent is **not** a second AI platform.

```text
Project / Agent
        ↓
Versioned AI Capability Contract  (v1.0)
        ↓
CapabilityProvider  (Yasin-AI or mock)
```

## Contract

- `CapabilityRequest` — capability, `contract_version="1.0"`, input, parameters,
  timeout, execution_id, agent_id, request_id
- `CapabilityResponse` — success, output, error_code, usage, provider, model,
  latency_ms

Capabilities: `inference`, `structured_generation`, `classification`,
`summarization`, `tool_selection`, `embedding`.

## Provider independence

- `CapabilityProvider` ABC
- `MockCapabilityProvider` — default, no credentials
- `ConfigurableCapabilityProvider` — named provider/model, still in-process

Core `ExecutionRuntime` runs without any capability client.

## Gates

1. Client `allowed_capabilities`
2. `ExecutionRuntime.check_capability` when `execution_id` is set
3. Agent loadout capabilities when `memory_manager` + `agent_id` are set

## Observability

Every invoke emits `ai.capability` on the shared EventEmitter.

## Out of scope

Real network calls to Yasin-AI. Wire a provider that implements
`CapabilityProvider.invoke` when credentials exist.
