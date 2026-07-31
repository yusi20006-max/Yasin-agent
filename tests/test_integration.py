"""
tests/test_integration.py
تست‌های یکپارچه‌سازی پکیج agent_platform با Yasin-Core SDK.
"""

import pytest
from yasin_core.sdk import YasinCoreClient, get_current_context
from agent_platform import (
    AgentConfig,
    AgentRegistry,
    TemplatePlanner,
    ToolRunner,
    Step,
    YasinCoreAgentAdapter,
    register_all_agents,
    save_agent_memory,
    get_agent_memory,
    get_active_client,
    register_tool_via_sdk,
    discover_tools_via_sdk,
    register_plugin_via_sdk,
    discover_plugins_via_sdk,
    execute_plugin_via_sdk,
)


def test_core_client_initialization():
    client = YasinCoreClient()
    assert client.get_version() == "1.0.0"
    assert "Yasin Core SDK Client" in client.get_info()["name"]


def test_agent_registration_and_execution():
    # 1. Setup registry, planner, and tool runner
    tool_runner = ToolRunner()
    tool_runner.register("fetch", lambda context, previous_output=None, **_: "news-content")
    tool_runner.register("process", lambda context, previous_output=None, **_: f"processed({previous_output})")

    planner = TemplatePlanner()
    planner.register_template(
        "news_flow",
        [
            Step(name="fetch", tool="fetch"),
            Step(name="process", tool="process"),
        ]
    )

    agent_registry = AgentRegistry()
    agent_registry.register(
        AgentConfig(
            name="news_agent",
            goal="news_flow",
            description="Test News Agent",
            default_context={"init_var": "hello"}
        )
    )

    # 2. Setup YasinCoreClient
    client = YasinCoreClient()

    # 3. Register agent
    register_all_agents(client, agent_registry, planner, tool_runner)
    assert "news_agent" in client.list_agents()

    # 4. Create and execute task via Yasin-Core SDK Client
    task = client.create_task(id="task-001", name="news_agent", input_data={"extra_var": "world"})
    executed_task = client.execute_task(task)

    assert executed_task.status == "completed"
    assert executed_task.result == "processed(news-content)"
    assert executed_task.error is None


def test_memory_and_context_handling():
    # 1. Setup tool runner with tools that interact with memory and context
    tool_runner = ToolRunner()

    def memory_test_tool(context, previous_output=None, **_):
        # Read from active context
        ctx = get_current_context()
        assert ctx.get("agent_name") == "mem_agent"
        assert ctx.get("goal") == "mem_flow"

        # Access active client directly or via helper
        active_client = get_active_client()
        assert active_client is not None

        # Write to short-term memory
        save_agent_memory("step_one_key", "step_one_value", category="short-term")
        # Write to long-term memory
        save_agent_memory("step_one_lt", "long_term_val", category="long-term")

        # Read back shared variables from context
        assert ctx.get("shared_variables") is not None
        assert ctx.get("shared_variables").get("param") == "test-input"

        return "memory-saved"

    def memory_read_tool(context, previous_output=None, **_):
        # Read from memory
        st_val = get_agent_memory("step_one_key", category="short-term")
        lt_val = get_agent_memory("step_one_lt", category="long-term")

        assert st_val == "step_one_value"
        assert lt_val == "long_term_val"

        return f"st={st_val}, lt={lt_val}"

    tool_runner.register("mem_write", memory_test_tool)
    tool_runner.register("mem_read", memory_read_tool)

    planner = TemplatePlanner()
    planner.register_template(
        "mem_flow",
        [
            Step(name="mem_write", tool="mem_write"),
            Step(name="mem_read", tool="mem_read"),
        ]
    )

    agent_registry = AgentRegistry()
    agent_registry.register(
        AgentConfig(
            name="mem_agent",
            goal="mem_flow",
            description="Test Memory Agent"
        )
    )

    client = YasinCoreClient()
    register_all_agents(client, agent_registry, planner, tool_runner)

    task = client.create_task(id="task-002", name="mem_agent", input_data={"param": "test-input"})
    executed_task = client.execute_task(task)

    assert executed_task.status == "completed"
    assert executed_task.result == "st=step_one_value, lt=long_term_val"

    # Verify that execution history and metadata are recorded in context
    agent = client.get_agent("mem_agent")
    assert agent is not None


def test_agent_definition_integration_with_yasin_core():
    # 1. Setup tool runner with tools that inspect the agent definition variables in context
    tool_runner = ToolRunner()

    def inspect_context_tool(context, previous_output=None, **_):
        ctx = get_current_context()

        # Verify prompts and profiles are injected correctly in the active context
        system_prompt = ctx.get("system_prompt")
        user_prompt = ctx.get("user_prompt")
        profile = ctx.get("agent_profile")
        metadata = ctx.get("agent_metadata")
        config = ctx.get("agent_config")

        assert "You are Assistant Chef" in system_prompt
        assert profile["role"] == "Assistant Chef"
        assert profile["tone"] == "polite"
        assert "cook safely" in profile["instructions"]
        assert metadata["version"] == "2.3.1"
        assert config["model"] == "gpt-4-pro"
        assert config["temperature"] == 0.4

        return "inspection-passed"

    tool_runner.register("inspect", inspect_context_tool)

    planner = TemplatePlanner()
    planner.register_template(
        "inspect_flow",
        [
            Step(name="inspect", tool="inspect"),
        ]
    )

    data = {
        "chef_agent": {
            "goal": "inspect_flow",
            "description": "Culinary Helper",
            "metadata": {
                "version": "2.3.1",
                "author": "Yasin Kitchen Team"
            },
            "config": {
                "model": "gpt-4-pro",
                "temperature": 0.4
            },
            "profile": {
                "role": "Assistant Chef",
                "backstory": "A culinary assistant",
                "tone": "polite",
                "instructions": ["cook safely", "taste food"]
            },
            "prompt_handler": {
                "system_prompt_template": "You are {role}. Tone: {tone}. Instructions: {instructions}"
            }
        }
    }

    agent_registry = AgentRegistry.from_dict(data)

    client = YasinCoreClient()
    register_all_agents(client, agent_registry, planner, tool_runner)

    task = client.create_task(id="task-003", name="chef_agent", input_data={"extra": "data"})
    executed_task = client.execute_task(task)

    assert executed_task.status == "completed"
    assert executed_task.result == "inspection-passed"


def test_sdk_tool_discovery_registration_and_execution():
    client = YasinCoreClient()

    # 1. Tool discovery (initially empty)
    initial_tools = discover_tools_via_sdk(client)
    assert len(initial_tools) == 0

    # 2. Tool registration
    def custom_sdk_add(a: int, b: int) -> int:
        return a + b

    register_tool_via_sdk(client, custom_sdk_add)

    # Verify discovery after registration
    updated_tools = discover_tools_via_sdk(client)
    assert "custom_sdk_add" in updated_tools

    # 3. Tool execution via SDK client
    res = client.execute_tool("custom_sdk_add", a=5, b=12)
    assert res == 17

    # 4. Integrate with agent execution loop
    # Let's create an agent that uses "custom_sdk_add" tool.
    # Our new ToolRunner should dynamically find it on the active client in active_context!
    tool_runner = ToolRunner()  # No custom_sdk_add registered here!
    planner = TemplatePlanner()
    planner.register_template(
        "add_flow",
        [
            Step(name="add_step", tool="custom_sdk_add"),
        ]
    )

    agent_registry = AgentRegistry()
    agent_registry.register(
        AgentConfig(
            name="math_solver_agent",
            goal="add_flow",
            description="Solves math"
        )
    )

    register_all_agents(client, agent_registry, planner, tool_runner)

    # Execute task with input
    task = client.create_task(id="task-math", name="math_solver_agent", input_data={"a": 20, "b": 30})
    executed_task = client.execute_task(task)

    assert executed_task.status == "completed"
    assert executed_task.result == 50


def test_sdk_plugin_discovery_registration_and_usage():
    client = YasinCoreClient()

    # Define a custom Yasin-Core plugin
    from yasin_core.plugins import YasinPlugin

    class SampleIntegrationPlugin(YasinPlugin):
        name = "sample_integration"

        def start(self):
            self.started = True

        def stop(self):
            self.started = False

        def execute(self, input_data):
            return f"plugin_output:{input_data.get('val', '')}"

    plugin = SampleIntegrationPlugin()

    # 1. Plugin registration
    register_plugin_via_sdk(client, plugin)
    assert "sample_integration" in client.list_plugins()

    # 2. Plugin usage through SDK directly
    res = execute_plugin_via_sdk(client, "sample_integration", {"val": "hello"})
    assert res == "plugin_output:hello"

    # 3. Discover plugins using mock plugins dir (Plugin discovery)
    import tempfile
    import os
    with tempfile.TemporaryDirectory() as tmpdir:
        plugin_code = """
from yasin_core.plugins import YasinPlugin

class AutoDiscoveredIntegrationPlugin(YasinPlugin):
    name = "auto_discovered_integration"

    def start(self):
        pass

    def stop(self):
        pass

    def execute(self, input_data):
        return f"AutoIntegration: {input_data.get('val', '')}"
"""
        plugin_filepath = os.path.join(tmpdir, "discovered_integration_plugin.py")
        with open(plugin_filepath, "w", encoding="utf-8") as f:
            f.write(plugin_code)

        discover_plugins_via_sdk(client, plugins_dir=tmpdir)
        assert "auto_discovered_integration" in client.list_plugins()

        # Verify execution of discovered plugin
        res_discovered = execute_plugin_via_sdk(client, "auto_discovered_integration", {"val": "world"})
        assert res_discovered == "AutoIntegration: world"
