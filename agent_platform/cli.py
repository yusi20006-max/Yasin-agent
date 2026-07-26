"""
cli.py
قلاب اتصال به CLI اصلی YasinAI برای دستور جدید:

    yasin agent run <agent_name>

این فایل هیچ منطق تجاری ندارد؛ فقط AgentRegistry + TemplatePlanner +
Executor را به هم وصل می‌کند. رجیستر کردن ابزارها و templateهای واقعی
باید جای دیگری (مثلاً در نقطه‌ی راه‌اندازی برنامه) انجام شود و از طریق
`build_default_registries` یا تزریق مستقیم در اختیار این تابع قرار گیرد.

نکته: این ماژول دستور موجود `yasin agent create` را تغییر نمی‌دهد؛
فقط زیردستور `run` را اضافه می‌کند.
"""

from __future__ import annotations

from typing import Optional

from .agent_registry import AgentRegistry
from .executor import Executor
from .planner import TemplatePlanner
from .task import Task, TaskResult
from .tool_runner import ToolRunner


def run_agent(
    agent_name: str,
    agent_registry: AgentRegistry,
    planner: TemplatePlanner,
    tool_runner: ToolRunner,
    task_name: Optional[str] = None,
) -> TaskResult:
    """
    اجرای یک ایجنت با نام مشخص: goal آن را از registry می‌گیرد،
    پلن می‌سازد، و با Executor اجرا می‌کند.

    این تابع همان چیزی است که دستور CLI `yasin agent run <name>` باید
    صدا بزند.
    """
    config = agent_registry.get(agent_name)
    task = Task(
        name=task_name or agent_name,
        goal=config.goal,
        context=dict(config.default_context),
    )
    steps = planner.plan(config.goal)
    executor = Executor(tool_runner)
    return executor.run(task, steps)


def register_cli_command(cli_app) -> None:  # pragma: no cover - وابسته به فریم‌ورک CLI فعلی
    """
    نقطه‌ی الحاق به CLI موجود YasinAI.

    پیاده‌سازی دقیق بسته به فریم‌ورک CLI فعلی (click / argparse / typer)
    فرق می‌کند؛ این تابع عمداً به‌صورت placeholder گذاشته شده تا هنگام
    یکپارچه‌سازی با کد واقعی CLI تکمیل شود، بدون این‌که به منطق اصلی
    agent_platform وابستگی مستقیم اضافه کند.
    """
    raise NotImplementedError(
        "این تابع باید هنگام یکپارچه‌سازی با CLI فعلی YasinAI تکمیل شود."
    )
