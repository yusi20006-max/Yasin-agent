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
    """رجیستری ساده‌ی نام -> AgentConfig یا AgentDefinition."""

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
            # پشتیبانی از ساختارهای پیشرفته‌ی تعریف ایجنت (Agent Definition Layer)
            if any(k in cfg for k in ("metadata", "config", "profile", "prompt_handler")):
                from agent_platform.agent_definition import (
                    AgentDefinition,
                    AgentMetadata,
                    AgentConfiguration,
                    AgentProfile,
                    PromptHandler,
                )

                meta_data = cfg.get("metadata", {})
                metadata = AgentMetadata(
                    version=meta_data.get("version", "1.0.0"),
                    author=meta_data.get("author", "Yasin-Agent Developer"),
                    description=meta_data.get("description", cfg.get("description", "")),
                    tags=meta_data.get("tags", []),
                    custom_metadata=meta_data.get("custom_metadata", {}),
                )

                conf_data = cfg.get("config", {})
                config = AgentConfiguration(
                    model=conf_data.get("model", "default-model"),
                    temperature=conf_data.get("temperature", 0.7),
                    max_tokens=conf_data.get("max_tokens", 2048),
                    top_p=conf_data.get("top_p", 1.0),
                    timeout=conf_data.get("timeout", 30.0),
                    extra_config=conf_data.get("extra_config", {}),
                )

                prof_data = cfg.get("profile", {})
                profile = AgentProfile(
                    role=prof_data.get("role", ""),
                    backstory=prof_data.get("backstory", ""),
                    tone=prof_data.get("tone", "neutral"),
                    instructions=prof_data.get("instructions", []),
                )

                prompt_data = cfg.get("prompt_handler", {})
                prompt_handler = PromptHandler(
                    system_prompt_template=prompt_data.get("system_prompt_template"),
                    user_prompt_template=prompt_data.get("user_prompt_template"),
                    custom_templates=prompt_data.get("custom_templates"),
                )

                definition = AgentDefinition(
                    name=name,
                    goal=cfg["goal"],
                    description=cfg.get("description", ""),
                    default_context=cfg.get("default_context", {}),
                    metadata=metadata,
                    config=config,
                    profile=profile,
                    prompt_handler=prompt_handler,
                )
                registry.register(definition)
            else:
                registry.register(
                    AgentConfig(
                        name=name,
                        goal=cfg["goal"],
                        description=cfg.get("description", ""),
                        default_context=cfg.get("default_context", {}),
                    )
                )
        return registry
