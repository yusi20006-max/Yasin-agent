"""
Public in-process SDK surface expected by YasinHub ``agent_integration``.

Production Hub \u2194 Agent control remains authenticated HTTP
(``agent_platform.server`` / Hub ``HttpTransportClient``). This client is a
thin compatibility adapter over ``agent_platform.AgentRegistry`` for CLI and
doctor health checks.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from agent_platform.agent_registry import AgentConfig, AgentNotFoundError, AgentRegistry
from agent_platform import __version__ as _AGENT_VERSION


class YasinAgentClient:
    """Minimal in-process client matching YasinHub AgentIntegration expectations."""

    def __init__(self, registry: Optional[AgentRegistry] = None) -> None:
        self._registry = registry if registry is not None else AgentRegistry()
        self._running: Dict[str, bool] = {}

    @property
    def version(self) -> str:
        return str(_AGENT_VERSION)

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
            AgentConfig(name=name, goal=goal, description=description or "")
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
        return self._registry.list_names()
