"""
agent_platform
بسته‌ی اجرای وظایف چندمرحله‌ای برای YasinAI.

اجزای اصلی این پکیج مستقل از CLI و شبکه هستند تا در آینده (در صورت
تهیه‌ی VPS) بتوان یک لایه‌ی نازک FastAPI روی همین منطق کشید بدون
بازنویسی آن.
"""

from .agent_registry import AgentConfig, AgentNotFoundError, AgentRegistry
from .agent_definition import (
    AgentMetadata,
    AgentConfiguration,
    AgentProfile,
    PromptHandler,
    AgentDefinition,
)
from .executor import Executor
from .planner import Planner, Step, TemplatePlanner, UnknownGoalError
from .state_machine import InvalidTransitionError, StateMachine, TaskState
from .task import StepResult, Task, TaskResult
from .tool_runner import ToolNotFoundError, ToolRunner
from .integration import (
    YasinCoreAgentAdapter,
    get_active_client,
    save_agent_memory,
    get_agent_memory,
    register_all_agents,
    register_tool_via_sdk,
    discover_tools_via_sdk,
    register_plugin_via_sdk,
    discover_plugins_via_sdk,
    execute_plugin_via_sdk,
)
from .execution import (
    CapabilityDeniedError,
    EventEmitter,
    ExecutionEvent,
    ExecutionEventType,
    ExecutionRecord,
    ExecutionRuntime,
    ExecutionState,
    WorkspaceBound,
    make_workspace,
    redact_secrets,
)
from .harness import (
    CollaborationHarness,
    CollaborationResult,
    WorkerResult,
    WorkerSpec,
)

from .memory_context import (
    MemoryManager,
    ContextManager,
    Session,
    SessionManager,
)

__all__ = [
    "AgentConfig",
    "AgentNotFoundError",
    "AgentRegistry",
    "AgentMetadata",
    "AgentConfiguration",
    "AgentProfile",
    "PromptHandler",
    "AgentDefinition",
    "Executor",
    "Planner",
    "Step",
    "TemplatePlanner",
    "UnknownGoalError",
    "InvalidTransitionError",
    "StateMachine",
    "TaskState",
    "StepResult",
    "Task",
    "TaskResult",
    "ToolNotFoundError",
    "ToolRunner",
    "YasinCoreAgentAdapter",
    "get_active_client",
    "save_agent_memory",
    "get_agent_memory",
    "register_all_agents",
    "register_tool_via_sdk",
    "discover_tools_via_sdk",
    "register_plugin_via_sdk",
    "discover_plugins_via_sdk",
    "execute_plugin_via_sdk",
    "MemoryManager",
    "ContextManager",
    "Session",
    "SessionManager",
    "CapabilityDeniedError",
    "EventEmitter",
    "ExecutionEvent",
    "ExecutionEventType",
    "ExecutionRecord",
    "ExecutionRuntime",
    "ExecutionState",
    "WorkspaceBound",
    "make_workspace",
    "redact_secrets",
    "CollaborationHarness",
    "CollaborationResult",
    "WorkerResult",
    "WorkerSpec",
]

__version__ = "1.0.0"
