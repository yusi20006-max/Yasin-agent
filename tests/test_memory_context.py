"""
tests/test_memory_context.py
پوشش تست برای مدیریت حافظه، کانتکست و سشن‌ها در سطح اپلیکیشن برای agent_platform.
"""

from __future__ import annotations

import pytest
from yasin_core.sdk import YasinCoreClient, active_context, get_current_context
from agent_platform.integration import YasinCoreClient as MockYasinCoreClient
from agent_platform import (
    MemoryManager,
    ContextManager,
    Session,
    SessionManager,
)


def test_memory_manager_with_mock_client():
    client = MockYasinCoreClient()
    manager = MemoryManager(client)

    # Test short-term memory
    manager.save("test_key", "short_val", category="short-term")
    assert manager.get("test_key", category="short-term") == "short_val"
    assert manager.get("missing_key", "default", category="short-term") == "default"

    # Test long-term memory
    manager.save("lt_key", "long_val", category="long-term")
    assert manager.get("lt_key", category="long-term") == "long_val"


def test_memory_manager_with_real_client():
    client = YasinCoreClient()
    manager = MemoryManager(client)

    # Test short-term memory
    manager.save("test_key", "short_val_real", category="short-term")
    assert manager.get("test_key", category="short-term") == "short_val_real"

    # Test long-term memory
    manager.save("lt_key", "long_val_real", category="long-term")
    assert manager.get("lt_key", category="long-term") == "long_val_real"


def test_context_manager_with_mock_client():
    client = MockYasinCoreClient()
    manager = ContextManager(client)

    ctx = manager.create({"var": "val_mock"})
    assert ctx.get("var") == "val_mock"

    with manager.propagate(ctx):
        current = manager.get_current()
        assert current.get("var") == "val_mock"


def test_context_manager_with_real_client():
    client = YasinCoreClient()
    manager = ContextManager(client)

    ctx = manager.create({"var": "val_real"})
    assert ctx.get("var") == "val_real"

    with manager.propagate(ctx):
        current = manager.get_current()
        assert current.get("var") == "val_real"


def test_session_handling_and_isolation_with_mock_client():
    client = MockYasinCoreClient()
    session_mgr = SessionManager(client)

    # Create two separate sessions
    session1 = session_mgr.create_session("session_1", {"user": "ali"})
    session2 = session_mgr.create_session("session_2", {"user": "reza"})

    assert session_mgr.get_session("session_1") is session1
    assert session_mgr.get_session("session_2") is session2

    # Save memory to session1
    session1.save_short_term("role", "admin")
    session1.save_long_term("theme", "dark")

    # Save memory to session2
    session2.save_short_term("role", "user")
    session2.save_long_term("theme", "light")

    # Verify memory isolation (keys prefixed under the hood)
    assert session1.get_short_term("role") == "admin"
    assert session1.get_long_term("theme") == "dark"
    assert session2.get_short_term("role") == "user"
    assert session2.get_long_term("theme") == "light"

    # Verify context updating
    session1.update_context(language="fa")
    assert session1.get_context_value("language") == "fa"
    assert session1.get_context_value("user") == "ali"
    assert session1.get_context_value("session_id") == "session_1"

    # Verify context propagation
    with session1.run_with_context():
        current_ctx = get_current_context()
        assert current_ctx.get("session_id") == "session_1"
        assert current_ctx.get("user") == "ali"

    # Close session
    session_mgr.close_session("session_1")
    assert session_mgr.get_session("session_1") is None


def test_session_handling_and_isolation_with_real_client():
    client = YasinCoreClient()
    session_mgr = SessionManager(client)

    session1 = session_mgr.create_session("session_real_1", {"app": "portal"})
    session2 = session_mgr.create_session("session_real_2", {"app": "dashboard"})

    # Save to short-term memory
    session1.save_short_term("key", "val_1")
    session2.save_short_term("key", "val_2")

    assert session1.get_short_term("key") == "val_1"
    assert session2.get_short_term("key") == "val_2"

    # Verify context propagation
    with session1.run_with_context():
        current_ctx = get_current_context()
        assert current_ctx.get("session_id") == "session_real_1"
        assert current_ctx.get("app") == "portal"

    session_mgr.close_session("session_real_1")
    assert session_mgr.get_session("session_real_1") is None


def test_session_manager_duplicate_raises():
    session_mgr = SessionManager()
    session_mgr.create_session("sess_unique")
    with pytest.raises(ValueError):
        session_mgr.create_session("sess_unique")
