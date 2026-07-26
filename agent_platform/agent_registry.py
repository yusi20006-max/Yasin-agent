"""
agent_registry.py
نگهداری پیکربندی‌های نام‌گذاری‌شده‌ی ایجنت‌ها (agent_name -> goal + تنظیمات).

این لایه چیزی اجرا نمی‌کند؛ فقط map می‌کند که وقتی کاربر/CLI می‌گوید
"agent X را اجرا کن"، منظور کدام goal (template ثبت‌شده در Planner) است.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentConfig:
    """پیکربندی یک ایجنت با نام."""

    name: str
    goal: str
    description: str = ""
    default_context: Dict[str, Any] = field(default_factory=dict)


class AgentNotFoundError(Exception):
    """وقتی نام ایجنت درخواست‌شده در registry نباشد."""


class AgentRegistry:
    """رجیستری ساده‌ی نام -> AgentConfig."""

    def __init__(self) -> None:
        self._agents: Dict[str, AgentConfig] = {}

    def register(self, config: AgentConfig, overwrite: bool = False) -> None:
        if config.name in self._agents and not overwrite:
            raise ValueError(f"ایجنت '{config.name}' قبلاً ثبت شده است")
        self._agents[config.name] = config

    def get(self, name: str) -> AgentConfig:
        if name not in self._agents:
            raise AgentNotFoundError(
                f"ایجنت '{name}' پیدا نشد. ایجنت‌های موجود: {self.list_agents()}"
            )
        return self._agents[name]

    def list_agents(self) -> List[str]:
        return sorted(self._agents.keys())

    @classmethod
    def from_dict(cls, data: Dict[str, Dict[str, Any]]) -> "AgentRegistry":
        """
        ساخت registry از یک دیکشنری ساده (مثلاً بارگذاری‌شده از JSON/YAML):
            {"news_bot": {"goal": "read_translate_publish", "description": "..."}}
        """
        registry = cls()
        for name, cfg in data.items():
            registry.register(
                AgentConfig(
                    name=name,
                    goal=cfg["goal"],
                    description=cfg.get("description", ""),
                    default_context=cfg.get("default_context", {}),
                )
            )
        return registry
