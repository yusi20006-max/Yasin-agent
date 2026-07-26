"""
executor.py
اجرای ترتیبی مراحل یک پلن روی یک Task، با retry و توقف در صورت خطای
غیرقابل‌بازیابی. وضعیت Task از طریق StateMachine به‌روزرسانی می‌شود.
"""

from __future__ import annotations

from typing import List

from .planner import Step
from .state_machine import StateMachine, TaskState
from .task import StepResult, Task, TaskResult
from .tool_runner import ToolRunner


class Executor:
    """اجراکننده‌ی یک لیست از Stepها روی یک Task مشخص."""

    def __init__(self, tool_runner: ToolRunner) -> None:
        self._tool_runner = tool_runner

    def run(self, task: Task, steps: List[Step]) -> TaskResult:
        sm = StateMachine()
        sm.transition(TaskState.PLANNING)
        sm.transition(TaskState.RUNNING)

        step_results: List[StepResult] = []
        last_output = None

        for step in steps:
            attempts = 0
            max_attempts = max(1, step.max_retries + 1)
            step_ok = False
            step_error = None
            step_output = None

            while attempts < max_attempts:
                attempts += 1
                try:
                    call_args = dict(step.args)
                    # به هر step اجازه می‌دهیم به context مشترک و خروجی قبلی دسترسی داشته باشد
                    call_args.setdefault("context", task.context)
                    call_args.setdefault("previous_output", last_output)
                    step_output = self._tool_runner.run(step.tool, **call_args)

                    if step.validator is not None and not step.validator(step_output):
                        raise ValueError(f"خروجی step '{step.name}' اعتبارسنجی را رد کرد")

                    step_ok = True
                    break
                except Exception as exc:  # noqa: BLE001 - عمداً broad برای ثبت هر خطا
                    step_error = str(exc)
                    if attempts < max_attempts:
                        sm.transition(TaskState.RETRYING)
                        sm.transition(TaskState.RUNNING)

            step_results.append(
                StepResult(
                    step_name=step.name,
                    success=step_ok,
                    output=step_output,
                    error=step_error,
                    attempts=attempts,
                )
            )

            if not step_ok:
                sm.transition(TaskState.FAILED)
                return TaskResult(
                    task_id=task.task_id,
                    success=False,
                    output=last_output,
                    error=f"شکست در step '{step.name}': {step_error}",
                    step_results=step_results,
                )

            last_output = step_output
            task.update_context(**{f"{step.name}_output": step_output})

        sm.transition(TaskState.SUCCEEDED)
        return TaskResult(
            task_id=task.task_id,
            success=True,
            output=last_output,
            step_results=step_results,
        )
