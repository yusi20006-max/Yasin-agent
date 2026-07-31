import os
import sys
from types import ModuleType

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Dynamically mock yasin_core if it is not present in the environment (e.g. in clean CI environment)
try:
    import yasin_core
except ImportError:
    # Create mock yasin_core modules
    yasin_core_mod = ModuleType("yasin_core")
    sys.modules["yasin_core"] = yasin_core_mod

    yasin_core_context_mod = ModuleType("yasin_core.context")
    sys.modules["yasin_core.context"] = yasin_core_context_mod

    yasin_core_plugins_mod = ModuleType("yasin_core.plugins")
    class YasinPlugin:
        pass
    yasin_core_plugins_mod.YasinPlugin = YasinPlugin
    sys.modules["yasin_core.plugins"] = yasin_core_plugins_mod

    yasin_core_sdk_mod = ModuleType("yasin_core.sdk")

    # Import mock classes dynamically from our integration module
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
