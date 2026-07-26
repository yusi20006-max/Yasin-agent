"""
planner.py
تجزیه‌ی یک goal به لیستی از Stepهای قابل اجرا.

پیاده‌سازی فعلی: TemplatePlanner ساده و قانون‌محور — هر goal از قبل
به‌صورت یک template (لیست ثابتی از نام ابزارها) در registry تعریف
می‌شود. بعداً می‌توان پلنرهای پیشرفته‌تر (LLM-based) را جایگزین/اضافه
کرد بدون تغییر executor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class Step:
    """یک مرحله‌ی قابل اجرا در یک پلن."""

    name: str
    tool: str
    args: Dict[str, Any] = field(default_factory=dict)
    max_retries: int = 0
    # اگر تابع validator بدهید، خروجی step بعد از اجرا با آن اعتبارسنجی می‌شود
    validator: Optional[Callable[[Any], bool]] = None


class UnknownGoalError(Exception):
    """وقتی برای یک goal هیچ template ثبت نشده باشد."""


class Planner:
    """کلاس پایه برای پلنرها؛ برای extend کردن با استراتژی‌های دیگر."""

    def plan(self, goal: str, **kwargs: Any) -> List[Step]:  # pragma: no cover
        raise NotImplementedError


class TemplatePlanner(Planner):
    """پلنر ساده‌ی مبتنی بر template های از پیش تعریف‌شده."""

    def __init__(self) -> None:
        self._templates: Dict[str, List[Step]] = {}

    def register_template(self, goal: str, steps: List[Step], overwrite: bool = False) -> None:
        if goal in self._templates and not overwrite:
            raise ValueError(f"template برای goal '{goal}' قبلاً ثبت شده است")
        self._templates[goal] = steps

    def list_goals(self) -> List[str]:
        return sorted(self._templates.keys())

    def plan(self, goal: str, **kwargs: Any) -> List[Step]:
        if goal not in self._templates:
            raise UnknownGoalError(f"goal '{goal}' هیچ template ثبت‌شده‌ای ندارد")
        # هر بار یک کپی مستقل برمی‌گردانیم تا اجرای همزمان با هم تداخل نکنند
        return [
            Step(
                name=s.name,
                tool=s.tool,
                args=dict(s.args),
                max_retries=s.max_retries,
                validator=s.validator,
            )
            for s in self._templates[goal]
        ]
