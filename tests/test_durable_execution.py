"""Issue #32 — durable execution, recovery and resume."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_platform.execution import (
    ExecutionEventType,
    ExecutionRecord,
    ExecutionRuntime,
    ExecutionState,
    make_workspace,
    redact_secrets,
)
from agent_platform.persistence import (
    InMemoryExecutionStore,
    JsonFileExecutionStore,
)
from agent_platform.state_machine import InvalidTransitionError


def _runtime(tmp_path: Path | None = None) -> ExecutionRuntime:
    if tmp_path is None:
        return ExecutionRuntime(store=InMemoryExecutionStore())
    return ExecutionRuntime(store=JsonFileExecutionStore(tmp_path))


def test_persist_and_restore_inmemory():
    store = InMemoryExecutionStore()
    rt = ExecutionRuntime(store=store)
    rec = rt.create(
        task_id="task-1",
        session_id="sess-1",
        agent_id="agent-a",
        capabilities=["read"],
        metadata={"note": "hello"},
        workspace=make_workspace(scope="ws-scope"),
    )
    rt.start(rec.execution_id)
    rt.save_checkpoint(rec.execution_id, {"step": 2, "cursor": "abc"})

    payload = store.load(rec.execution_id)
    assert payload is not None
    assert payload["status"] == "running"
    assert payload["checkpoint"]["step"] == 2
    assert payload["session_id"] == "sess-1"
    assert payload["workspace"]["scope"] == "ws-scope"
    assert "read" in payload["capabilities"]

    restored = ExecutionRecord.from_dict(payload)
    assert restored.execution_id == rec.execution_id
    assert restored.status == ExecutionState.RUNNING
    assert restored.checkpoint == {"step": 2, "cursor": "abc"}
    assert restored.agent_id == "agent-a"


def test_json_file_persist_and_restore(tmp_path: Path):
    store = JsonFileExecutionStore(tmp_path)
    rt = ExecutionRuntime(store=store)
    rec = rt.create(task_id="t-file")
    rt.start(rec.execution_id)
    rt.pause(rec.execution_id)

    rt2 = ExecutionRuntime(store=store)
    recovered = rt2.recover(rec.execution_id)
    assert recovered.status == ExecutionState.PAUSED
    assert recovered.task_id == "t-file"
    assert recovered.execution_id == rec.execution_id


def test_restart_recovery_flow(tmp_path: Path):
    store = JsonFileExecutionStore(tmp_path)
    rt = ExecutionRuntime(store=store)
    a = rt.create(task_id="a")
    b = rt.create(task_id="b")
    rt.start(a.execution_id)
    rt.start(b.execution_id)
    rt.pause(a.execution_id)
    rt.complete(b.execution_id, result={"ok": True})

    rt2 = ExecutionRuntime(store=store)
    recovered = rt2.recover_all()
    ids = {r.execution_id for r in recovered}
    assert a.execution_id in ids
    assert b.execution_id in ids

    ra = rt2.get(a.execution_id)
    rb = rt2.get(b.execution_id)
    assert ra is not None and ra.status == ExecutionState.PAUSED
    assert rb is not None and rb.status == ExecutionState.SUCCEEDED


def test_resume_from_paused_and_queued(tmp_path: Path):
    rt = _runtime(tmp_path)
    paused = rt.create(task_id="p")
    rt.start(paused.execution_id)
    rt.pause(paused.execution_id)
    rt.save_checkpoint(paused.execution_id, {"step": 3})

    queued = rt.create(task_id="q")

    rt2 = ExecutionRuntime(store=rt._store)
    rt2.recover_all()
    r1 = rt2.resume(paused.execution_id)
    assert r1.status == ExecutionState.RUNNING
    assert r1.checkpoint == {"step": 3}

    r2 = rt2.resume(queued.execution_id)
    assert r2.status == ExecutionState.RUNNING


def test_duplicate_recovery_idempotent(tmp_path: Path):
    rt = _runtime(tmp_path)
    rec = rt.create(task_id="dup")
    rt.start(rec.execution_id)

    rt2 = ExecutionRuntime(store=rt._store)
    a = rt2.recover(rec.execution_id)
    b = rt2.recover(rec.execution_id)
    assert a is b
    assert len(rt2.list_executions()) == 1


def test_terminal_cannot_resume(tmp_path: Path):
    rt = _runtime(tmp_path)
    for terminal_fn in (
        lambda r: rt.complete(r.execution_id),
        lambda r: rt.fail(r.execution_id, "boom"),
        lambda r: rt.cancel(r.execution_id),
    ):
        rec = rt.create(task_id="term")
        rt.start(rec.execution_id)
        terminal_fn(rec)
        rt2 = ExecutionRuntime(store=rt._store)
        rt2.recover(rec.execution_id)
        with pytest.raises(InvalidTransitionError):
            rt2.resume(rec.execution_id)


def test_failed_and_cancelled_recovery_preserves_status(tmp_path: Path):
    rt = _runtime(tmp_path)
    failed = rt.create(task_id="f")
    rt.start(failed.execution_id)
    rt.fail(failed.execution_id, "err")

    cancelled = rt.create(task_id="c")
    rt.start(cancelled.execution_id)
    rt.cancel(cancelled.execution_id)

    rt2 = ExecutionRuntime(store=rt._store)
    rt2.recover_all()
    assert rt2.get(failed.execution_id).status == ExecutionState.FAILED
    assert rt2.get(failed.execution_id).error == "err"
    assert rt2.get(cancelled.execution_id).status == ExecutionState.CANCELLED


def test_event_ordering_preserved_across_lifecycle():
    rt = ExecutionRuntime(store=InMemoryExecutionStore())
    rec = rt.create(task_id="ev")
    rt.start(rec.execution_id)
    rt.pause(rec.execution_id)
    rt.resume(rec.execution_id)
    rt.complete(rec.execution_id, result=1)

    events = rt.events.history(execution_id=rec.execution_id)
    seqs = [e.sequence for e in events]
    assert seqs == sorted(seqs)
    types = [e.event_type for e in events]
    assert ExecutionEventType.CREATED.value in types
    assert ExecutionEventType.STARTED.value in types
    assert ExecutionEventType.PAUSED.value in types
    assert ExecutionEventType.RESUMED.value in types
    assert ExecutionEventType.COMPLETED.value in types


def test_event_dedup_by_id():
    rt = ExecutionRuntime()
    rec = rt.create(task_id="d")
    events = rt.events.history(execution_id=rec.execution_id)
    ids = [e.event_id for e in events]
    assert len(ids) == len(set(ids))


def test_workspace_and_capability_preservation(tmp_path: Path):
    rt = _runtime(tmp_path)
    ws = make_workspace(workspace_id="ws-fixed", path="/tmp/ws", scope="project")
    rec = rt.create(
        task_id="cap",
        workspace=ws,
        capabilities=["search", "fetch"],
        agent_id="agent-x",
        session_id="sess-x",
    )
    rt.start(rec.execution_id)
    rt.pause(rec.execution_id)

    rt2 = ExecutionRuntime(store=rt._store)
    got = rt2.recover(rec.execution_id)
    assert got.workspace.workspace_id == "ws-fixed"
    assert got.workspace.path == "/tmp/ws"
    assert got.workspace.scope == "project"
    assert set(got.capabilities) == {"search", "fetch"}
    assert got.agent_id == "agent-x"
    assert got.session_id == "sess-x"


def test_secret_redaction_in_persisted_snapshot(tmp_path: Path):
    rt = _runtime(tmp_path)
    rec = rt.create(
        task_id="sec",
        metadata={"api_key": "sk-secret-1234567890abcdef", "note": "ok"},
    )
    rt.start(rec.execution_id)
    rt.complete(rec.execution_id, result={"token": "bearer xyz", "value": 1})

    payload = rt._store.load(rec.execution_id)
    assert payload is not None
    assert payload["metadata"]["api_key"] == "***"
    assert payload["metadata"]["note"] == "ok"


def test_checkpoint_merge_and_replace(tmp_path: Path):
    rt = _runtime(tmp_path)
    rec = rt.create(task_id="ck")
    rt.start(rec.execution_id)
    rt.save_checkpoint(rec.execution_id, {"a": 1})
    rt.save_checkpoint(rec.execution_id, {"b": 2}, merge=True)
    assert rt.get(rec.execution_id).checkpoint == {"a": 1, "b": 2}
    rt.save_checkpoint(rec.execution_id, {"c": 3}, merge=False)
    assert rt.get(rec.execution_id).checkpoint == {"c": 3}


def test_checkpoint_on_terminal_rejected(tmp_path: Path):
    rt = _runtime(tmp_path)
    rec = rt.create(task_id="ck-term")
    rt.start(rec.execution_id)
    rt.complete(rec.execution_id)
    with pytest.raises(InvalidTransitionError):
        rt.save_checkpoint(rec.execution_id, {"x": 1})


def test_backward_compatible_no_store():
    rt = ExecutionRuntime()
    rec = rt.create(task_id="compat")
    rt.start(rec.execution_id)
    rt.pause(rec.execution_id)
    rt.resume(rec.execution_id)
    rt.complete(rec.execution_id, result=42)
    assert rt.get(rec.execution_id).status == ExecutionState.SUCCEEDED
    assert rt.get(rec.execution_id).result == 42
    with pytest.raises(KeyError):
        rt.recover("missing-id")


def test_list_recoverable(tmp_path: Path):
    rt = _runtime(tmp_path)
    a = rt.create(task_id="a")
    b = rt.create(task_id="b")
    rt.start(a.execution_id)
    rt.start(b.execution_id)
    rt.complete(b.execution_id)
    recoverable = rt.list_recoverable()
    ids = {r.execution_id for r in recoverable}
    assert a.execution_id in ids
    assert b.execution_id not in ids


def test_cancel_semantics_preserved(tmp_path: Path):
    rt = _runtime(tmp_path)
    rec = rt.create(task_id="cancel-me")
    rt.start(rec.execution_id)
    rt.cancel(rec.execution_id)
    assert rec.status == ExecutionState.CANCELLED
    assert rec.cancel_requested is True
    rt2 = ExecutionRuntime(store=rt._store)
    got = rt2.recover(rec.execution_id)
    assert got.status == ExecutionState.CANCELLED
    assert got.cancel_requested is True


def test_corrupted_snapshot_skipped(tmp_path: Path):
    store = JsonFileExecutionStore(tmp_path)
    bad = tmp_path / "broken.json"
    bad.write_text("{not-json", encoding="utf-8")
    rt = ExecutionRuntime(store=store)
    assert rt.recover_all() == []
