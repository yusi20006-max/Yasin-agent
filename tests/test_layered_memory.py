"""Issue #34 — layered memory + agent loadout + ACL."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_platform.memory import (
    AgentLoadout,
    AssetType,
    InMemoryMemoryStore,
    JsonFileMemoryStore,
    LayeredMemoryManager,
    LoadoutBinding,
    MemoryAccessDenied,
    MemoryLayer,
)


def test_add_get_update_remove():
    mm = LayeredMemoryManager()
    a = mm.add_memory("hello", layer=MemoryLayer.L1_ATOM, tags=["greet"])
    assert a.version == 1
    got = mm.get_memory(a.asset_id)
    assert got is not None
    assert got.content == "hello"
    mm.update_memory(a.asset_id, content="hello2")
    assert mm.get_memory(a.asset_id).content == "hello2"
    assert mm.get_memory(a.asset_id).version == 2
    mm.remove_memory(a.asset_id)
    assert mm.get_memory(a.asset_id) is None


def test_layers():
    mm = LayeredMemoryManager()
    for layer in MemoryLayer:
        a = mm.add_memory(f"c-{layer.value}", layer=layer)
        assert a.layer == layer
    found = mm.search_memory(layer=MemoryLayer.L3_CORE)
    assert len(found) == 1


def test_search_by_tags_and_query():
    mm = LayeredMemoryManager()
    mm.add_memory("alpha beta", tags=["t1", "t2"])
    mm.add_memory("gamma", tags=["t2"])
    assert len(mm.search_memory(tags=["t1"])) == 1
    assert len(mm.search_memory(query="gamma")) == 1


def test_loadout_attach_detach_acl():
    mm = LayeredMemoryManager()
    mem = mm.add_memory("secret-fact", layer=MemoryLayer.L1_ATOM)
    lo = mm.create_loadout("agent-a", capabilities=["read"])
    # Without attach — denied
    with pytest.raises(MemoryAccessDenied):
        mm.get_memory(mem.asset_id, agent_id="agent-a")
    mm.attach_memory(lo.loadout_id, mem.asset_id, allow_read=True, allow_write=False)
    # Now readable
    got = mm.get_memory(mem.asset_id, agent_id="agent-a")
    assert got.content == "secret-fact"
    # Write denied
    with pytest.raises(MemoryAccessDenied):
        mm.update_memory(mem.asset_id, content="x", agent_id="agent-a")
    mm.attach_memory(lo.loadout_id, mem.asset_id, allow_read=True, allow_write=True)
    mm.update_memory(mem.asset_id, content="updated", agent_id="agent-a")
    assert mm.get_memory(mem.asset_id).content == "updated"
    mm.detach_memory(lo.loadout_id, mem.asset_id)
    with pytest.raises(MemoryAccessDenied):
        mm.get_memory(mem.asset_id, agent_id="agent-a")


def test_no_cross_agent_leakage():
    mm = LayeredMemoryManager()
    mem = mm.add_memory("private", owner_agent_id="agent-a")
    lo_a = mm.create_loadout("agent-a")
    mm.attach_memory(lo_a.loadout_id, mem.asset_id)
    lo_b = mm.create_loadout("agent-b")
    # agent-b has no binding
    with pytest.raises(MemoryAccessDenied):
        mm.get_memory(mem.asset_id, agent_id="agent-b")
    # search scoped
    results = mm.search_memory(agent_id="agent-b")
    assert all(r.asset_id != mem.asset_id for r in results)
    results_a = mm.search_memory(agent_id="agent-a")
    assert any(r.asset_id == mem.asset_id for r in results_a)


def test_validate_loadout():
    mm = LayeredMemoryManager()
    lo = mm.create_loadout("agent-x")
    problems = mm.validate_loadout(lo.loadout_id)
    assert problems == []
    mm.attach_memory(lo.loadout_id, "missing-id") if False else None
    # attach requires existing asset
    with pytest.raises(KeyError):
        mm.attach_memory(lo.loadout_id, "does-not-exist")


def test_persistence_roundtrip(tmp_path: Path):
    store = JsonFileMemoryStore(tmp_path)
    mm1 = LayeredMemoryManager(store=store)
    mem = mm1.add_memory("persist-me", layer=MemoryLayer.L2_SCENARIO, tags=["s"])
    lo = mm1.create_loadout("agent-p")
    mm1.attach_memory(lo.loadout_id, mem.asset_id)

    mm2 = LayeredMemoryManager(store=store)
    got = mm2.get_memory(mem.asset_id)
    assert got is not None
    assert got.content == "persist-me"
    lo2 = mm2.load_loadout(lo.loadout_id)
    assert lo2 is not None
    assert any(b.asset_id == mem.asset_id for b in lo2.bindings)


def test_activate_loadout():
    mm = LayeredMemoryManager()
    lo1 = mm.create_loadout("agent-z", activate=True)
    lo2 = mm.create_loadout("agent-z", activate=False, loadout_id="lo-alt")
    assert mm.get_active_loadout("agent-z").loadout_id == lo1.loadout_id
    mm.activate_loadout("agent-z", lo2.loadout_id)
    assert mm.get_active_loadout("agent-z").loadout_id == lo2.loadout_id


def test_capabilities_on_loadout():
    mm = LayeredMemoryManager()
    lo = mm.create_loadout("agent-c", capabilities=["research", "infer"])
    assert lo.allows_capability("research")
    assert not lo.allows_capability("shell")


def test_versioning():
    mm = LayeredMemoryManager()
    a = mm.add_memory("v1")
    assert a.version == 1
    mm.update_memory(a.asset_id, content="v2")
    assert mm.get_memory(a.asset_id).version == 2


def test_secret_redaction_in_asset():
    mm = LayeredMemoryManager()
    a = mm.add_memory("x", metadata={"api_key": "sk-abc1234567890123"})
    d = a.as_dict()
    assert d["metadata"]["api_key"] == "***"
