"""Android ARM64 & Termux compatibility contract tests (Issue #51)."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from agent_platform.observability import (
    get_android_api_level,
    get_system_info,
    is_android,
    is_termux,
)

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import httpx
from fastapi.testclient import TestClient
from agent_platform.server.app import create_app, main

TOKEN = "test-termux-token-51"


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_termux_and_android_environment_detection(monkeypatch) -> None:
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
    monkeypatch.setenv("ANDROID_API_LEVEL", "30")

    assert is_termux() is True
    assert is_android() is True
    assert get_android_api_level() == 30

    info = get_system_info()
    assert info["is_termux"] is True
    assert info["is_android"] is True
    assert info["android_api_level"] == 30
    assert "python_version" in info
    assert "arch" in info


def test_non_android_environment_detection(monkeypatch) -> None:
    monkeypatch.delenv("PREFIX", raising=False)
    monkeypatch.delenv("ANDROID_API_LEVEL", raising=False)
    monkeypatch.delenv("SL4A_API_LEVEL", raising=False)
    monkeypatch.delenv("ANDROID_ARGUMENT", raising=False)
    monkeypatch.delenv("ANDROID_ROOT", raising=False)
    monkeypatch.delenv("ANDROID_DATA", raising=False)

    with patch("sys.platform", "linux"), patch("os.path.exists", return_value=False):
        assert is_termux() is False
        assert is_android() is False
        assert get_android_api_level() is None


def test_health_and_ready_system_metadata() -> None:
    app = create_app(service_token=TOKEN)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    r_health = client.get("/v1/health", headers=headers)
    assert r_health.status_code == 200
    body_health = r_health.json()
    assert "system" in body_health
    assert "python_version" in body_health["system"]
    assert "is_android" in body_health["system"]

    r_ready = client.get("/v1/ready", headers=headers)
    assert r_ready.status_code == 200
    body_ready = r_ready.json()
    assert body_ready["ready"] is True
    assert "system" in body_ready
    assert "is_termux" in body_ready["system"]


def test_main_requires_service_token(monkeypatch) -> None:
    monkeypatch.delenv("YASIN_AGENT_SERVICE_TOKEN", raising=False)
    with pytest.raises(SystemExit) as exc:
        main()
    assert "YASIN_AGENT_SERVICE_TOKEN is required" in str(exc.value)


def test_noninteractive_cli_execution() -> None:
    res = subprocess.run(
        [sys.executable, "-m", "agent_platform.cli", "agent", "run", "news_bot"],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=10,
    )
    assert res.returncode == 0
    assert "news_bot" in res.stdout


def test_server_real_process_lifecycle_start_stop_restart_pid() -> None:
    """Verifies real process startup, PID existence, health/ready checks, stop, and restart PID change."""
    port1 = _get_free_port()
    env = dict(os.environ)
    env["YASIN_AGENT_SERVICE_TOKEN"] = TOKEN
    env["YASIN_AGENT_HOST"] = "127.0.0.1"
    env["YASIN_AGENT_PORT"] = str(port1)

    # 1. Start server process
    proc1 = subprocess.Popen(
        [sys.executable, "-m", "agent_platform.server"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    pid1 = proc1.pid
    assert pid1 > 0

    base_url1 = f"http://127.0.0.1:{port1}"
    client = httpx.Client(base_url=base_url1, headers={"Authorization": f"Bearer {TOKEN}"})

    up = False
    for _ in range(50):
        try:
            r = client.get("/v1/ready", timeout=1.0)
            if r.status_code == 200 and r.json().get("ready") is True:
                up = True
                break
        except Exception:
            time.sleep(0.1)

    assert up is True, "Server failed to start and respond to /v1/ready"

    r_health = client.get("/v1/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "healthy"

    # 2. Stop server process
    proc1.send_signal(signal.SIGTERM)
    proc1.wait(timeout=5)
    assert proc1.poll() is not None

    with pytest.raises(Exception):
        client.get("/v1/ready", timeout=0.5)

    client.close()

    # 3. Restart server on new process / port
    port2 = _get_free_port()
    env["YASIN_AGENT_PORT"] = str(port2)

    proc2 = subprocess.Popen(
        [sys.executable, "-m", "agent_platform.server"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    pid2 = proc2.pid
    assert pid2 > 0
    assert pid2 != pid1

    base_url2 = f"http://127.0.0.1:{port2}"
    client2 = httpx.Client(base_url=base_url2, headers={"Authorization": f"Bearer {TOKEN}"})

    up2 = False
    for _ in range(50):
        try:
            r = client2.get("/v1/ready", timeout=1.0)
            if r.status_code == 200 and r.json().get("ready") is True:
                up2 = True
                break
        except Exception:
            time.sleep(0.1)

    assert up2 is True

    proc2.send_signal(signal.SIGTERM)
    proc2.wait(timeout=5)
    client2.close()
