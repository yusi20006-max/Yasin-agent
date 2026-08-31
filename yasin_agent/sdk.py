"""
Public in-process SDK surface expected by YasinHub ``agent_integration``.

Production Hub → Agent control remains authenticated HTTP
(``agent_platform.server`` / Hub ``HttpTransportClient``). This client is a
thin compatibility adapter over ``agent_platform.AgentRegistry`` for CLI and
doctor health checks.

For CLI/doctor use, the compatibility registry is durable by default. The
path can be overridden with ``registry_path`` or ``YASIN_AGENT_REGISTRY_PATH``.
Pass an explicit ``AgentRegistry`` to keep fully in-memory/test behaviour.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Union

from agent_platform.agent_registry import (
    AgentConfig,
    AgentNotFoundError,
    AgentRegistry,
)
from agent_platform import __version__ as _AGENT_VERSION


_DEFAULT_REGISTRY_PATH = Path("~/.yasin/agent_registry.json").expanduser()


class YasinAgentClient:
    """Minimal client matching YasinHub AgentIntegration expectations."""

    def __init__(
        self,
        registry: Optional[AgentRegistry] = None,
        *,
        registry_path: Optional[Union[str, os.PathLike]] = None,
    ) -> None:
        if registry is not None:
            self._registry = registry
        else:
            path = registry_path or os.environ.get("YASIN_AGENT_REGISTRY_PATH")
            self._registry = AgentRegistry.from_path(path or _DEFAULT_REGISTRY_PATH)
        self._running: Dict[str, bool] = {}

    @property
    def version(self) -> str:
        return str(_AGENT_VERSION)

    @property
    def registry(self) -> AgentRegistry:
        return self._registry

    def register_agent(self, name: str, description: str = "") -> bool:
        name = (name or "").strip()
        if not name:
            return False
        goal = name
        try:
            existing = self._registry.get(name)
            goal = existing.goal or name
        except AgentNotFoundError:
            pass
        self._registry.register(
            AgentConfig(name=name, goal=goal, description=description or ""),
            overwrite=True,
        )
        return True

    def get_agent_status(self, name: str) -> Dict[str, Any]:
        name = (name or "").strip()
        try:
            cfg = self._registry.get(name)
        except AgentNotFoundError:
            return {
                "name": name,
                "status": "unknown",
                "error": f"agent {name!r} not found",
            }
        running = self._running.get(name, False)
        return {
            "name": cfg.name,
            "status": "running" if running else "registered",
            "goal": cfg.goal,
            "description": cfg.description,
            "version": self.version,
        }

    def start_agent(self, name: str) -> bool:
        name = (name or "").strip()
        try:
            self._registry.get(name)
        except AgentNotFoundError:
            return False
        self._running[name] = True
        return True

    def stop_agent(self, name: str) -> bool:
        name = (name or "").strip()
        try:
            self._registry.get(name)
        except AgentNotFoundError:
            return False
        self._running[name] = False
        return True

    def restart_agent(self, name: str) -> bool:
        if not self.stop_agent(name):
            return False
        return self.start_agent(name)

    def check_agent_health(self, name: str) -> Dict[str, Any]:
        status = self.get_agent_status(name)
        if status.get("error"):
            return {
                "name": name,
                "status": "unhealthy",
                "error": status.get("error"),
            }
        return {
            "name": name,
            "status": "healthy",
            "agent_status": status.get("status"),
            "version": self.version,
        }

    def list_agents(self) -> list:
        return self._registry.list_agents()
