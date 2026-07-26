"""
agent_platform
بسته‌ی اجرای وظایف چندمرحله‌ای برای YasinAI.

اجزای اصلی این پکیج مستقل از CLI و شبکه هستند تا در آینده (در صورت
تهیه‌ی VPS) بتوان یک لایه‌ی نازک FastAPI روی همین منطق کشید بدون
بازنویسی آن.
"""

from .agent_registry import AgentConfig, AgentNotFoundError, AgentRegistry
from .executor import Executor
from .planner import Planner, Step, TemplatePlanner, UnknownGoalError
from .state_machine import InvalidTransitionError, StateMachine, TaskState
from .task import StepResult, Task, TaskResult
from .tool_runner import ToolNotFoundError, ToolRunner

__all__ = [
    "AgentConfig",
    "AgentNotFoundError",
    "AgentRegistry",
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
]

__version__ = "0.1.0"
