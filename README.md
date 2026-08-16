# agent_platform (Yasin-Agent) — v1.0.0 Stable

Independent multi-step agent execution package for the **Yasin ecosystem**.

According to YASIN-DOCS ADR-001:

- **Yasin-Agent** owns agent planning, workflow, tools, sessions, and execution semantics.
- **Yasin-Core** is the generic runtime/SDK foundation (this package integrates via adapter).
- **Yasin-AI** is the canonical shared AI capability platform — consumers use only public contracts (`yasinai.contracts` / `yasinai.services`). Optional generation/memory via Yasin-AI is tracked in issue **#19** and is **DEFERRED** until needed.

This repository is **not** a submodule or component of Yasin-AI. It provides the agent layer between agent definitions, workflow, tools, plugins, memory/context, and the Yasin-Core SDK.

Design goal: full independence of the processing layer from CLI or network transport (transport-agnostic), so a web layer (e.g. FastAPI) can sit on top cleanly.

---

## Key features (v1.0 Stable)

- **Agent Definition Layer**: structured agents with metadata, model/tech config, persona/profile, and advanced prompt templates (`PromptHandler`).
- **Workflow / Planner**: sequential plans via `TemplatePlanner` and managed task state lifecycle (`StateMachine`).
- **Executor**: step-by-step execution with output validators and retries.
- **Tool System**: dynamic registration/invocation with signature adaptation (`ToolRunner`); tools registered into the Core SDK client.
- **Plugin System**: auto-discovery from configured directories; register/run via Yasin-Core SDK client.
- **Memory & Context**: isolated, thread-aware contexts (`ContextManager`) and short/long-term memory spaces (`MemoryManager`).
- **Session Handling**: interactive sessions with isolated context/memory (`SessionManager`).
- **SDK adapter**: `YasinCoreAgentAdapter` maps platform agents to valid Yasin-Core agents.

---

## Package layout

```
agent_platform/
├── agent_platform/
│   ├── __init__.py          # version + public exports
│   ├── agent_definition.py  # Metadata, Config, Profile, PromptHandler
│   ├── agent_registry.py    # agent registration
│   ├── task.py              # Task, TaskResult, StepResult
│   ├── state_machine.py     # PENDING → PLANNING → RUNNING → SUCCEEDED/FAILED
│   ├── planner.py           # Step, TemplatePlanner
│   ├── executor.py          # sequential steps + retry + validation
│   ├── tool_runner.py       # tool registry and invocation
│   ├── memory_context.py    # memory, context, isolated sessions
│   ├── integration.py       # Yasin-Core SDK adapter + fallback
│   └── cli.py               # CLI helpers
├── tests/
│   ├── test_agent_platform.py
│   ├── test_memory_context.py
│   └── test_integration.py
├── conftest.py
└── README.md
```

---

## Local install and tests

```bash
pip install pytest click
# optional: editable install of Yasin-Core if integrating against a real SDK
pytest tests/ -v
```

---

## Examples

### 1. Simple workflow

```python
from agent_platform import TemplatePlanner, ToolRunner, Task, Executor, Step

tool_runner = ToolRunner()
tool_runner.register("fetch", lambda context, previous_output=None, **_: "raw-news")
tool_runner.register("translate", lambda context, previous_output=None, **_: f"fa({previous_output})")

planner = TemplatePlanner()
planner.register_template("read_translate", [
    Step(name="fetch", tool="fetch"),
    Step(name="translate", tool="translate"),
])

task = Task(name="demo", goal="read_translate")
result = Executor(tool_runner).run(task, planner.plan("read_translate"))

print(result.summary())
print("final:", result.output)  # fa(raw-news)
```

### 2. Sessions and isolated memory

```python
from agent_platform import SessionManager

session_mgr = SessionManager()
session = session_mgr.create_session("session_1001", {"user": "ali"})
session.save_short_term("selected_topic", "AI Technologies")
session.save_long_term("theme_preference", "dark")

print(session.get_short_term("selected_topic"), session.get_long_term("theme_preference"))

with session.run_with_context():
    pass  # get_current_context() available inside
```

### 3. Integration with Yasin-Core SDK

```python
from yasin_core.sdk import YasinCoreClient
from agent_platform import AgentRegistry, TemplatePlanner, ToolRunner, register_all_agents

agent_registry = AgentRegistry()
planner = TemplatePlanner()
tool_runner = ToolRunner()
client = YasinCoreClient()

register_all_agents(client, agent_registry, planner, tool_runner)

task = client.create_task(id="task-001", name="news_bot")
executed_task = client.execute_task(task)
print("status:", executed_task.status)
```

---

## CLI

```bash
python -m agent_platform.cli agent run news_bot
```

`register_cli_command(cli_app)` attaches `agent run` to click/argparse-style CLIs when present.

---

## Ecosystem boundaries

| Project | Role |
|---------|------|
| Yasin-Core | Runtime/SDK foundation |
| Yasin-AI | Shared AI contracts (optional for Agent — #19 deferred) |
| **Yasin-Agent (this repo)** | Planning, workflow, tools, sessions |
| YasinHub | Status/health reporting CLI |
| Yasin-cli | Unified operator command surface (target) |
| YasinRelay / Feed / Press | Domain content pipelines |
