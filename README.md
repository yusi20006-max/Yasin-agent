# Yasin-Agent

Yasin-Agent is the agent runtime platform for the Yasin AI Ecosystem, built on Yasin-Core's public SDK.

## Compatibility import (`yasin_agent.sdk`)

YasinHub and older tooling may import:

```python
from yasin_agent.sdk import YasinAgentClient
```

This is a **thin compatibility surface** over `agent_platform` (registry/status/health). The primary package remains `agent_platform`. Production Hub orchestration uses authenticated HTTP (`HubAgentClient` / Agent server), not this in-process client.

### Agent Registry persistence

`AgentRegistry()` remains in-memory by default for library/unit-test use. The compatibility `YasinAgentClient()` uses a small atomic JSON registry by default so YasinHub CLI/Doctor can observe registrations across separate processes. Override the location with `YASIN_AGENT_REGISTRY_PATH` or the `registry_path=` constructor argument.

```bash
export YASIN_AGENT_REGISTRY_PATH="$HOME/.yasin/agent_registry.json"
```

Or explicitly:

```python
from agent_platform.agent_registry import AgentRegistry
from yasin_agent.sdk import YasinAgentClient

client = YasinAgentClient(registry=AgentRegistry.from_path("/var/lib/yasin/agents.json"))
```

The registry store redacts secret-looking keys/values and uses atomic file replacement. It is intended for local/single-node CLI state, not multi-writer distributed coordination.

---

## YasinHub integration

```bash
export YASINHUB_AGENT_BASE_URL=http://127.0.0.1:8080
export YASINHUB_AGENT_SERVICE_TOKEN=shared-secret
```

Hub flow: create execution → poll status/events → pause/resume/cancel → fleets.

See [docs/HUB_AGENT_E2E.md](docs/HUB_AGENT_E2E.md) and [docs/HTTP_RUNTIME_ADAPTER.md](docs/HTTP_RUNTIME_ADAPTER.md).

Python helper:

```python
from agent_platform.server.hub_client import HubAgentClient
client = HubAgentClient(base_url="http://127.0.0.1:8080", token="shared-secret")
client.health()
rec = client.create_execution("task-1", start=True, capabilities=["read"])
```

---

## Persistence & recovery

Optional stores: in-memory (default) or JSON directory.

```python
from agent_platform import ExecutionRuntime
from agent_platform.persistence import JsonFileExecutionStore

rt = ExecutionRuntime(store=JsonFileExecutionStore("/var/lib/yasin/executions"))
# After restart:
rt.recover_all()
```

Docs: [docs/DURABLE_EXECUTION.md](docs/DURABLE_EXECUTION.md)
