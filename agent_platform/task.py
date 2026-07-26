"""
task.py
تعریف واحدهای اصلی کار: Task و TaskResult.

این ماژول هیچ وابستگی‌ای به CLI یا شبکه ندارد؛ فقط ساختار داده و
منطق پایه‌ی مربوط به یک "وظیفه" را تعریف می‌کند.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class StepResult:
    """نتیجه‌ی اجرای یک مرحله (step) از پلن."""

    step_name: str
    success: bool
    output: Any = None
    error: Optional[str] = None
    attempts: int = 1


@dataclass
class TaskResult:
    """نتیجه‌ی نهایی اجرای یک Task کامل."""

    task_id: str
    success: bool
    output: Any = None
    error: Optional[str] = None
    step_results: List[StepResult] = field(default_factory=list)

    def summary(self) -> str:
        status = "SUCCESS" if self.success else "FAILED"
        return f"[{status}] task={self.task_id} steps={len(self.step_results)}"


@dataclass
class Task:
    """
    یک وظیفه‌ی چندمرحله‌ای.

    goal: هدف انسانی‌خوان (مثلاً "read_translate_summarize_publish")
    context: داده‌های ورودی/خروجی مشترک بین مراحل (state مشترک)
    """

    name: str
    goal: str
    context: Dict[str, Any] = field(default_factory=dict)
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    metadata: Dict[str, Any] = field(default_factory=dict)

    def update_context(self, **kwargs: Any) -> None:
        self.context.update(kwargs)

    def __repr__(self) -> str:  # pragma: no cover - صرفاً نمایشی
        return f"Task(id={self.task_id}, name={self.name!r}, goal={self.goal!r})"
