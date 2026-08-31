"""Durable AgentRegistry regression coverage."""
from __future__ import annotations

import json
import os
import subprocess
import sys

from agent_platform.agent_registry import (
    AgentConfig,
    AgentRegistry,
    JsonFileAgentRegistryStore,
)
from yasin_agent.sdk import YasinAgentClient


def test_json_registry_roundtrip(tmp_path) -> None:
    path = tmp_path / "agents.json"
    reg = AgentRegistry.from_path(path)
    reg.register(
        AgentConfig(
            name="news_bot",
            goal="read_translate_publish",
            description="News agent",
            default_context={"token": "sk-abcdefghijklmnopqrstuvwxyz"},
        )
    )

    loaded = AgentRegistry.from_path(path)
    cfg = loaded.get("news_bot")
    assert cfg.goal == "read_translate_publish"
    assert cfg.description == "News agent"
    assert cfg.default_context["token"] == "***"
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in path.read_text(encoding="utf-8")


def test_corrupt_registry_is_treated_as_empty(tmp_path) -> None:
    path = tmp_path / "agents.json"
    path.write_text("{not-json", encoding="utf-8")
    reg = AgentRegistry.from_path(path)
    assert reg.list_agents() == []


def test_registry_write_is_atomic_and_valid_json(tmp_path) -> None:
    path = tmp_path / "agents.json"
    reg = AgentRegistry.from_path(path)
    reg.register(AgentConfig(name="one", goal="one"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["agents"]["one"]["goal"] == "one"
    assert not list(tmp_path.glob("*.tmp"))


def test_sdk_cross_process_persistence(tmp_path) -> None:
    path = tmp_path / "agents.json"
    env = os.environ.copy()
    env["YASIN_AGENT_REGISTRY_PATH"] = str(path)
    script = (
        "from yasin_agent.sdk import YasinAgentClient; "
        "c=YasinAgentClient(); "
        "assert c.register_agent('cross-process', 'persistent'); "
        "print(c.get_agent_status('cross-process')['status'])"
    )
    first = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "registered" in first.stdout

    second_script = (
        "from yasin_agent.sdk import YasinAgentClient; "
        "c=YasinAgentClient(); "
        "print(c.get_agent_status('cross-process')['status'])"
    )
    second = subprocess.run(
        [sys.executable, "-c", second_script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert second.stdout.strip() == "registered"


def test_sdk_explicit_in_memory_registry_remains_supported() -> None:
    registry = AgentRegistry()
    client = YasinAgentClient(registry=registry)
    client.register_agent("local-only")
    assert client.get_agent_status("local-only")["status"] == "registered"
    assert registry.list_agents() == ["local-only"]
