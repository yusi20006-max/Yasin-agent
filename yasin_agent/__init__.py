"""
Compatibility namespace for ecosystem consumers that import ``yasin_agent``.

The primary package remains ``agent_platform`` (project name ``yasin-agent``).
This namespace provides a stable import path for YasinHub and other tools that
historically expected ``yasin_agent.sdk.YasinAgentClient``.
"""

from agent_platform import __version__ as __version__  # noqa: F401

__all__ = ["__version__"]
