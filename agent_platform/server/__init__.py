"""Optional HTTP Execution Runtime adapter for YasinHub.

Importing ``agent_platform`` does not require this package. Install the
optional extra::

    pip install 'yasin-agent[server]'

Then run::

    python -m agent_platform.server
"""

from __future__ import annotations

__all__ = ["create_app", "run_server"]


def __getattr__(name: str):
    if name in {"create_app", "run_server"}:
        from agent_platform.server.app import create_app, run_server

        return {"create_app": create_app, "run_server": run_server}[name]
    raise AttributeError(name)
