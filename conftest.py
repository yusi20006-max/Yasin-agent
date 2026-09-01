import os
import sys
from types import ModuleType

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Dynamically mock the public SDK if Yasin-Core is not installed (clean CI / standalone).
# Only yasin_core.sdk is mocked — Agent must not depend on Core internals.
try:
    import yasin_core.sdk  # noqa: F401
except ImportError:
    yasin_core_mod = ModuleType("yasin_core")
    sys.modules["yasin_core"] = yasin_core_mod

    yasin_core_sdk_mod = ModuleType("yasin_core.sdk")

    from agent_platform.integration import (
        YasinCoreClient,
        get_current_context,
        active_context,
        BaseAgent,
        BaseTool,
        FunctionTool,
        tool,
        PluginExecutionBridge,
    )

    yasin_core_sdk_mod.YasinCoreClient = YasinCoreClient
    yasin_core_sdk_mod.get_current_context = get_current_context
    yasin_core_sdk_mod.active_context = active_context
    yasin_core_sdk_mod.BaseAgent = BaseAgent
    yasin_core_sdk_mod.BaseTool = BaseTool
    yasin_core_sdk_mod.FunctionTool = FunctionTool
    yasin_core_sdk_mod.tool = tool
    yasin_core_sdk_mod.PluginExecutionBridge = PluginExecutionBridge

    sys.modules["yasin_core.sdk"] = yasin_core_sdk_mod
