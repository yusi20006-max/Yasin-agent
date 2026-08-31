"""
agent_registry.py
نگهداری پیکربندی‌های نام‌گذاری‌شده‌ی ایجنت‌ها (agent_name -> goal + تنظیمات).

این لایه چیزی اجرا نمی‌کند؛ فقط map می‌کند که وقتی کاربر/CLI می‌گوید
"agent X را اجرا کن"، منظور کدام goal (template ثبت‌شده در Planner) است.

The registry remains in-memory by default. A small JSON-backed store is
available for CLI/doctor and single-node deployments that need cross-process
persistence.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union


_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|token|secret|password|credential|authorization|bearer|private[_-]?key)",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._\-+=/]{8,}|sk-[a-z0-9]{16,}|ghp_[a-z0-9]{20,})"
)


def _redact(value: Any, *, depth: int = 0) -> Any:
    """Redact secret-looking registry metadata before it reaches disk."""
    if depth > 8:
        return "<max-depth>"
    if isinstance(value, dict):
        return {
            str(k): "***" if _SECRET_KEY_RE.search(str(k)) else _redact(v, depth=depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(v, depth=depth + 1) for v in value]
    if isinstance(value, str):
        return _SECRET_VALUE_RE.sub("***", value)
    return value


@dataclass
class AgentConfig:
    """پیکربندی یک ایجنت با نام."""

    name: str
    goal: str
    description: str = ""
    default_context: Dict[str, Any] = field(default_factory=dict)


class AgentNotFoundError(Exception):
    """وقتی نام ایجنت درخواست‌شده در registry نباشد."""


class AgentRegistryStore(ABC):
    """Provider-agnostic persistence contract for AgentRegistry."""

    @abstractmethod
    def load(self) -> Dict[str, Dict[str, Any]]:
        """Load the complete registry definition map."""

    @abstractmethod
    def save(self, data: Mapping[str, Mapping[str, Any]]) -> None:
        """Atomically persist the complete registry definition map."""


class JsonFileAgentRegistryStore(AgentRegistryStore):
    """Atomic JSON-file store for single-node/Termux registry persistence."""

    def __init__(self, path: Union[str, os.PathLike]) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def load(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            if not self.path.is_file():
                return {}
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
            if not isinstance(raw, dict):
                return {}
            agents = raw.get("agents", raw)
            if not isinstance(agents, dict):
                return {}
            out: Dict[str, Dict[str, Any]] = {}
            for name, cfg in agents.items():
                if isinstance(name, str) and isinstance(cfg, dict):
                    out[name] = dict(cfg)
            return out

    def save(self, data: Mapping[str, Mapping[str, Any]]) -> None:
        payload = {
            "version": 1,
            "agents": _redact({str(k): dict(v) for k, v in data.items()}),
        }
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        with self._lock:
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent)
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                    tmp.write(encoded)
                    tmp.flush()
                    os.fsync(tmp.fileno())
                os.replace(tmp_name, self.path)
            finally:
                try:
                    os.unlink(tmp_name)
                except FileNotFoundError:
                    pass


class AgentRegistry:
    """رجیستری ساده‌ی نام -> AgentConfig یا AgentDefinition."""

    def __init__(self, store: Optional[AgentRegistryStore] = None) -> None:
        self._agents: Dict[str, AgentConfig] = {}
        self._store = store
        if self._store is not None:
            self._load_from_store()

    @classmethod
    def from_path(cls, path: Union[str, os.PathLike]) -> "AgentRegistry":
        """Create a registry backed by a JSON file."""
        return cls(store=JsonFileAgentRegistryStore(path))

    @property
    def store(self) -> Optional[AgentRegistryStore]:
        return self._store

    def reload(self) -> None:
        """Reload persisted definitions into this registry."""
        self._load_from_store()

    def register(self, config: AgentConfig, overwrite: bool = False) -> None:
        if config.name in self._agents and not overwrite:
            raise ValueError(f"ایجنت '{config.name}' قبلاً ثبت شده است")
        self._agents[config.name] = config
        self._persist()

    def get(self, name: str) -> AgentConfig:
        if name not in self._agents:
            raise AgentNotFoundError(
                f"ایجنت '{name}' پیدا نشد. ایجنت‌های موجود: {self.list_agents()}"
            )
        return self._agents[name]

    def list_agents(self) -> List[str]:
        return sorted(self._agents.keys())

    def list_names(self) -> List[str]:
        """Compatibility alias used by the YasinAgentClient surface."""
        return self.list_agents()

    def _config_to_dict(self, config: AgentConfig) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "goal": config.goal,
            "description": config.description,
            "default_context": _redact(dict(config.default_context)),
        }
        # Preserve the richer AgentDefinition layer when present.
        for attr in ("metadata", "config", "profile", "prompt_handler"):
            value = getattr(config, attr, None)
            if value is None:
                continue
            if attr == "prompt_handler":
                data[attr] = {
                    "system_prompt_template": value.system_prompt_template,
                    "user_prompt_template": value.user_prompt_template,
                    "custom_templates": dict(value.custom_templates),
                }
            elif hasattr(value, "__dict__"):
                data[attr] = _redact(dict(value.__dict__))
        return data

    def _load_from_store(self) -> None:
        if self._store is None:
            return
        data = self._store.load()
        if not data:
            self._agents = {}
            return
        loaded = self.from_dict(data)
        self._agents = loaded._agents

    def _persist(self) -> None:
        if self._store is None:
            return
        data = {name: self._config_to_dict(cfg) for name, cfg in self._agents.items()}
        self._store.save(data)

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


__all__ = [
    "AgentConfig",
    "AgentNotFoundError",
    "AgentRegistryStore",
    "JsonFileAgentRegistryStore",
    "AgentRegistry",
]
