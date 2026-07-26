"""
tool_runner.py
رجیستری ابزارهای نام‌گذاری‌شده که مراحل (steps) می‌توانند فراخوانی کنند.

هر ابزار یک تابع/callable ساده است با امضای دلخواه؛ فراخوانی از طریق نام
انجام می‌شود تا planner/executor نیازی به import مستقیم توابع نداشته باشند.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List


class ToolNotFoundError(Exception):
    """وقتی ابزاری با نام درخواست‌شده ثبت نشده باشد."""


class ToolRunner:
    """رجیستری ساده‌ی نام -> callable."""

    def __init__(self) -> None:
        self._tools: Dict[str, Callable[..., Any]] = {}

    def register(self, name: str, func: Callable[..., Any], overwrite: bool = False) -> None:
        if name in self._tools and not overwrite:
            raise ValueError(f"ابزار '{name}' قبلاً ثبت شده است (overwrite=True بدهید تا جایگزین شود)")
        self._tools[name] = func

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self) -> List[str]:
        return sorted(self._tools.keys())

    def run(self, name: str, *args: Any, **kwargs: Any) -> Any:
        if name not in self._tools:
            raise ToolNotFoundError(f"ابزار '{name}' ثبت نشده است. ابزارهای موجود: {self.list_tools()}")
        return self._tools[name](*args, **kwargs)
