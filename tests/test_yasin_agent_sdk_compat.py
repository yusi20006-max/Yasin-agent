"""Compatibility surface: yasin_agent.sdk.YasinAgentClient for YasinHub."""
from __future__ import annotations

from yasin_agent.sdk import YasinAgentClient


def test_import_and_construct():
    client = YasinAgentClient()
    assert client.version


def test_register_status_health_lifecycle():
    client = YasinAgentClient()
    assert client.register_agent("demo", "test agent") is True
    st = client.get_agent_status("demo")
    assert st["name"] == "demo"
    assert st["status"] == "registered"
    assert client.start_agent("demo") is True
    assert client.get_agent_status("demo")["status"] == "running"
    health = client.check_agent_health("demo")
    assert health["status"] == "healthy"
    assert client.stop_agent("demo") is True
    assert client.get_agent_status("demo")["status"] == "registered"
    assert client.restart_agent("demo") is True
    assert client.get_agent_status("demo")["status"] == "running"


def test_unknown_agent():
    client = YasinAgentClient()
    st = client.get_agent_status("missing")
    assert st["status"] == "unknown"
    assert "error" in st
    assert client.start_agent("missing") is False
    health = client.check_agent_health("missing")
    assert health["status"] == "unhealthy"
