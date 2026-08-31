# yasin-agent (Yasin-Agent) — v1.1.0

Independent multi-step agent **execution runtime** for the **Yasin ecosystem**.

| Component | Role |
|-----------|------|
| **Yasin-Agent** | Planning, workflow, tools, sessions, execution, jobs, memory/loadout |
| **Yasin-Core** | Generic runtime/SDK foundation (optional adapter) |
| **Yasin-AI** | Canonical AI platform — Agent uses capability contracts only |
| **YasinHub** | Orchestration / observation over authenticated HTTP |

Design goal: core runtime works **without** FastAPI, external AI, or network research providers.

---

## Requirements

- Python **3.9 – 3.13**
- Core: `click`
- Server (optional): `fastapi`, `uvicorn`
- Tests: `pytest`, `httpx` (+ server extras for HTTP tests)

---

## Install

```bash
# Core only
pip install -e .

# With HTTP server (YasinHub)
pip install -e ".[server]"

# Tests
pip install -e ".[test-server]"
pytest tests/ -q
```

Clean clone → install → test must succeed with no personal secrets or machine paths.

---

## Configuration

| Variable | Purpose |
|----------|---------|
| `YASIN_AGENT_SERVICE_TOKEN` | Shared bearer token for Hub ↔ Agent HTTP |
| `YASINHUB_AGENT_BASE_URL` | Hub-side base URL (e.g. `http://127.0.0.1:8080`) |
| `YASINHUB_AGENT_SERVICE_TOKEN` | Same shared secret on Hub |

Never commit tokens. Prefer environment or secret manager.

---

## Run HTTP server

```bash
export YASIN_AGENT_SERVICE_TOKEN=shared-secret
python -m agent_platform.server
# or: yasin-agent-server
```

Health: `GET /v1/health` with `Authorization: Bearer shared-secret`.

---

## Compatibility import (`yasin_agent.sdk`)

YasinHub and older tooling may import:

```python
from yasin_agent.sdk import YasinAgentClient
```

This is a **thin compatibility surface** over `agent_platform` (registry/status/health). The primary package remains `agent_platform`. Production Hub orchestration uses authenticated HTTP (`HubAgentClient` / Agent server), not this in-process client.

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

---

## Scheduling (jobs)

```python
from agent_platform import ExecutionRuntime, JobScheduler, ScheduleSpec, RetryPolicy
from agent_platform.jobs import InMemoryJobStore
from agent_platform.persistence import InMemoryExecutionStore

rt = ExecutionRuntime(store=InMemoryExecutionStore())
sched = JobScheduler(rt, store=InMemoryJobStore(), max_concurrent=4)
job = sched.create_job(task_id="nightly", retry=RetryPolicy(max_attempts=3), run_immediately=True)
```

Docs: [docs/JOBS_AND_SCHEDULING.md](docs/JOBS_AND_SCHEDULING.md)

---

## Memory & Agent Loadout

Layers: **L0** Conversation · **L1** Atom · **L2** Scenario · **L3** Core/Persona  
Loadout ACL binds memory/skills/capabilities per agent.

Docs: [docs/MEMORY_AND_LOADOUT.md](docs/MEMORY_AND_LOADOUT.md)

---

## Yasin-AI capability boundary

```python
from agent_platform import CapabilityClient, CapabilityRequest, CapabilityName, MockCapabilityProvider
client = CapabilityClient(MockCapabilityProvider())
resp = client.invoke(CapabilityRequest(capability=CapabilityName.INFERENCE, input="hi"))
```

Docs: [docs/YASIN_AI_CAPABILITY.md](docs/YASIN_AI_CAPABILITY.md)

---

## Research boundary

Explicit capability — not unrestricted network.

```python
from agent_platform import ResearchClient, ResearchRequest, MockResearchProvider
client = ResearchClient(MockResearchProvider())
result = client.search(ResearchRequest(query="yasin"))
```

Docs: [docs/RESEARCH_BOUNDARY.md](docs/RESEARCH_BOUNDARY.md)

---

## Observability & security

- Metrics / diagnostics: [docs/OBSERVABILITY.md](docs/OBSERVABILITY.md)
- Auth, isolation, validation: [docs/SECURITY.md](docs/SECURITY.md)

---

## Package layout

```
agent_platform/     # primary public package
yasin_agent/        # compatibility import for Hub (sdk.YasinAgentClient)
  execution.py      # ExecutionRuntime lifecycle + recovery
  persistence.py    # ExecutionStore backends
  jobs.py           # JobScheduler
  memory.py         # Layered memory + loadout
  ai_capability.py  # Yasin-AI contract
  research.py       # Research boundary
  observability.py  # Metrics / diagnostics
  security.py       # Validation / isolation helpers
  server/           # Optional FastAPI adapter + hub_client
tests/
docs/
```

---

## Production deployment (summary)

1. Python 3.9+ on host or container  
2. `pip install 'yasin-agent[server]'`  
3. Set `YASIN_AGENT_SERVICE_TOKEN`  
4. Mount durable store path if required  
5. Run behind TLS reverse proxy  
6. Probe `/v1/health` and `/v1/ready`  
7. Point YasinHub at the service URL with the same token  

See [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) and [CHANGELOG.md](CHANGELOG.md).

---

## License / ecosystem

Part of the Yasin AI Ecosystem. Agent does **not** replace Yasin-AI.
