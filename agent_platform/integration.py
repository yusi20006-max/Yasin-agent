"""
integration.py
یکپارچه‌سازی پکیج agent_platform با Yasin-Core SDK v1.0.0.

این ماژول آداپتورها و ابزارهای لازم برای اجرای ایجنت‌های agent_platform
توسط کلاینت YasinCoreClient را فراهم می‌کند.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    import yasin_core.context
    from yasin_core.sdk import (
        BaseAgent,
        YasinCoreClient,
        active_context,
        get_current_context,
        BaseTool,
        FunctionTool,
        tool,
        PluginExecutionBridge,
    )
except ImportError:
    # Fallback to simulated objects if yasin_core is not present (for standalone/mock tests)
    class BaseAgent:  # type: ignore
        def __init__(self, name: str, description: str = "", tools: Optional[list[Any]] = None):
            self.name = name
            self.description = description
            self.running = False
            self.tools = tools or []

    class YasinCoreClient:  # type: ignore
        def __init__(self, short_term_memory=None, long_term_memory=None):
            self._tools = {}
            self._plugins = {}
            self._agents = {}
        def register_tool(self, tool):
            self._tools[tool.name] = tool
        def get_tool(self, name):
            return self._tools.get(name)
        def remove_tool(self, name):
            return self._tools.pop(name, None)
        def list_tools(self):
            return list(self._tools.keys())
        def execute_tool(self, name, *args, **kwargs):
            return self._tools[name](*args, **kwargs)
        def register_plugin(self, plugin):
            self._plugins[plugin.name] = plugin
        def get_plugin(self, name):
            return self._plugins.get(name)
        def list_plugins(self):
            return list(self._plugins.keys())
        def discover_plugins(self, plugins_dir="plugins"):
            pass
        def register_agent(self, agent):
            self._agents[agent.name] = agent
        def list_agents(self):
            return list(self._agents.keys())

    class BaseTool:
        def __init__(self, name: str, description: str = "", args_schema: Optional[Dict[str, Any]] = None):
            self.name = name
            self.description = description
            self.args_schema = args_schema or {}
        def execute(self, *args, **kwargs):
            pass
        def __call__(self, *args, **kwargs):
            return self.execute(*args, **kwargs)

    class FunctionTool(BaseTool):
        def __init__(self, func, name=None, description=None, args_schema=None):
            self.func = func
            super().__init__(name or func.__name__, description or func.__doc__ or "", args_schema)
        def execute(self, *args, **kwargs):
            return self.func(*args, **kwargs)

    def tool(arg=None, **kwargs):
        if callable(arg):
            return FunctionTool(arg)
        def decorator(func):
            return FunctionTool(func, **kwargs)
        return decorator

    class PluginExecutionBridge(BaseAgent):
        def __init__(self, name, plugin_registry, plugin_name, description=""):
            super().__init__(name, description)
            self.plugin_registry = plugin_registry
            self.plugin_name = plugin_name
        def execute(self, input_data):
            plugin = self.plugin_registry.get(self.plugin_name)
            if plugin and hasattr(plugin, "execute"):
                return plugin.execute(input_data)
            return None

    def active_context(context: Any) -> Any:  # type: ignore
        import contextlib
        @contextlib.contextmanager
        def _dummy():
            yield context
        return _dummy()

    def get_current_context() -> Any:  # type: ignore
        class DummyContext:
            def get(self, key: str, default: Any = None) -> Any:
                return default
            def set(self, key: str, value: Any) -> None:
                pass
        return DummyContext()


from agent_platform.executor import Executor as AgentExecutor
from agent_platform.task import Task as AgentTask


class YasinCoreAgentAdapter(BaseAgent):
    """
    آداپتور جهت معرفی یک ایجنت از agent_platform به عنوان یک BaseAgent در Yasin-Core.
    """

    def __init__(
        self,
        agent_config: Any,
        agent_registry: Any,
        planner: Any,
        tool_runner: Any,
        client: Optional[YasinCoreClient] = None,
    ):
        super().__init__(
            name=agent_config.name,
            description=agent_config.description,
        )
        self.agent_config = agent_config
        self.agent_registry = agent_registry
        self.planner = planner
        self.tool_runner = tool_runner
        self.client = client

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def execute(self, input_data: Dict[str, Any]) -> Any:
        # ساخت یا بازیابی Context بر اساس ساختار Yasin-Core
        context_data = dict(self.agent_config.default_context)
        context_data.update(input_data)

        if self.client and hasattr(self.client, "create_context"):
            core_context = self.client.create_context(context_data)
        else:
            try:
                core_context = yasin_core.context.Context(context_data)
            except NameError:
                class MockContext:
                    def __init__(self, d):
                        self._data = d
                    def get(self, k, default=None):
                        return self._data.get(k, default)
                    def set(self, k, v):
                        self._data[k] = v
                core_context = MockContext(context_data)

        # تنظیم متادیتا و متغیرهای مشترک
        core_context.set("client", self.client)
        core_context.set("agent_name", self.name)
        core_context.set("goal", self.agent_config.goal)
        core_context.set("execution_history", [])
        core_context.set("shared_variables", core_context._data)
        core_context.set("task_metadata", {
            "agent_name": self.name,
            "goal": self.agent_config.goal,
        })

        # در صورت وجود تعریف پیشرفته، پرکردن متادیتا، پیکربندی، پروفایل و پرامپت‌ها در کانتکست
        from agent_platform.agent_definition import AgentDefinition
        if isinstance(self.agent_config, AgentDefinition):
            # رندر پرامپت‌ها
            system_prompt = self.agent_config.prompt_handler.render_system_prompt(self.agent_config.profile)
            user_prompt = self.agent_config.prompt_handler.render_user_prompt(input_data)

            # قرار دادن آنها در کانتکست جهت استفاده در ابزارها یا LLM
            core_context.set("system_prompt", system_prompt)
            core_context.set("user_prompt", user_prompt)
            core_context.set("agent_profile", {
                "role": self.agent_config.profile.role,
                "backstory": self.agent_config.profile.backstory,
                "tone": self.agent_config.profile.tone,
                "instructions": self.agent_config.profile.instructions,
            })
            core_context.set("agent_metadata", {
                "version": self.agent_config.metadata.version,
                "author": self.agent_config.metadata.author,
                "tags": self.agent_config.metadata.tags,
                "custom_metadata": self.agent_config.metadata.custom_metadata,
            })
            core_context.set("agent_config", {
                "model": self.agent_config.config.model,
                "temperature": self.agent_config.config.temperature,
                "max_tokens": self.agent_config.config.max_tokens,
                "top_p": self.agent_config.config.top_p,
                "timeout": self.agent_config.config.timeout,
                "extra_config": self.agent_config.config.extra_config,
            })

        # اجرای گام‌ها در قالب اکتیو کانتکست
        with active_context(core_context):
            agent_task = AgentTask(
                name=self.agent_config.name,
                goal=self.agent_config.goal,
                context=core_context._data,
            )
            steps = self.planner.plan(self.agent_config.goal)
            executor = AgentExecutor(self.tool_runner)
            result = executor.run(agent_task, steps)

            # ثبت تاریخچه اجرا در کانتکست برای اهداف عیب‌یابی یا LLM
            history = core_context.get("execution_history") or []
            for step_res in result.step_results:
                history.append({
                    "step_name": step_res.step_name,
                    "success": step_res.success,
                    "output": step_res.output,
                    "error": step_res.error,
                    "attempts": step_res.attempts,
                })
            core_context.set("execution_history", history)

            if not result.success:
                raise RuntimeError(result.error)

            return result.output


def get_active_client() -> Optional[YasinCoreClient]:
    """بازیابی کلاینت فعال از کانتکست فعلی."""
    try:
        ctx = get_current_context()
        return ctx.get("client")
    except Exception:
        return None


def save_agent_memory(key: str, value: Any, category: str = "short-term") -> None:
    """ذخیره مقدار در حافظه کلاینت فعال."""
    client = get_active_client()
    if client and hasattr(client, "save_memory"):
        client.save_memory(key, value, category=category)


def get_agent_memory(key: str, default: Any = None, category: str = "short-term") -> Any:
    """بازیابی مقدار از حافظه کلاینت فعال."""
    client = get_active_client()
    if client and hasattr(client, "get_memory"):
        return client.get_memory(key, default=default, category=category)
    return default


def register_all_agents(
    client: YasinCoreClient,
    agent_registry: Any,
    planner: Any,
    tool_runner: Any,
) -> None:
    """ثبت خودکار تمامی ایجنت‌های موجود در رجیستری در کلاینت Yasin-Core."""
    # ثبت ابزارهای ToolRunner در Yasin-Core جهت برقراری یکپارچگی ابزارها
    if hasattr(client, "register_tool"):
        for tool_name in tool_runner.list_tools():
            if hasattr(client, "get_tool") and client.get_tool(tool_name) is None:
                # Wrap tool_runner's tool into a FunctionTool and register
                tool_func = tool_runner._tools[tool_name]
                if isinstance(tool_func, BaseTool):
                    client.register_tool(tool_func)
                else:
                    client.register_tool(FunctionTool(tool_func, name=tool_name))

    for agent_name in agent_registry.list_agents():
        config = agent_registry.get(agent_name)
        adapter = YasinCoreAgentAdapter(
            agent_config=config,
            agent_registry=agent_registry,
            planner=planner,
            tool_runner=tool_runner,
            client=client,
        )
        client.register_agent(adapter)


# توابع کمکی یکپارچه‌سازی ابزارها و پلاگین‌ها طبق SDK عمومی Yasin-Core

def register_tool_via_sdk(client: YasinCoreClient, tool_obj: Any) -> None:
    """ثبت ابزار در کلاینت Core با استفاده از SDK عمومی."""
    if isinstance(tool_obj, BaseTool):
        client.register_tool(tool_obj)
    elif callable(tool_obj):
        name = getattr(tool_obj, "__name__", "custom_tool")
        client.register_tool(FunctionTool(tool_obj, name=name))
    else:
        raise ValueError("Invalid tool object. Must be callable or inherit from BaseTool.")


def discover_tools_via_sdk(client: YasinCoreClient) -> List[str]:
    """یافتن و لیست کردن ابزارهای ثبت‌شده در هسته."""
    if hasattr(client, "list_tools"):
        return client.list_tools()
    return []


def register_plugin_via_sdk(client: YasinCoreClient, plugin: Any) -> None:
    """ثبت یک پلاگین در کلاینت Core با استفاده از SDK عمومی."""
    if hasattr(client, "register_plugin"):
        client.register_plugin(plugin)


def discover_plugins_via_sdk(client: YasinCoreClient, plugins_dir: str = "plugins") -> None:
    """کشف پلاگین‌ها از دایرکتوری مشخص با استفاده از SDK عمومی."""
    if hasattr(client, "discover_plugins"):
        client.discover_plugins(plugins_dir)


def execute_plugin_via_sdk(client: YasinCoreClient, plugin_name: str, input_data: Dict[str, Any]) -> Any:
    """اجرای مستقیم یک پلاگین با استفاده از SDK عمومی."""
    if hasattr(client, "get_plugin"):
        plugin = client.get_plugin(plugin_name)
        if not plugin:
            raise ValueError(f"Plugin '{plugin_name}' not found.")
        if hasattr(plugin, "execute"):
            return plugin.execute(input_data)
        elif hasattr(plugin, "run"):
            return plugin.run(input_data)
        elif callable(plugin):
            return plugin(input_data)
        else:
            raise AttributeError(f"Plugin '{plugin_name}' is not executable.")
    raise ValueError("Client does not support get_plugin.")
