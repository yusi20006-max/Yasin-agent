"""Issue #26 — observable execution workspace boundary."""

from __future__ import annotations

import pytest

from agent_platform.execution import (
    CapabilityDeniedError,
    EventEmitter,
    ExecutionEventType,
    ExecutionRuntime,
    ExecutionState,
    make_workspace,
    redact_secrets,
)
from agent_platform.state_machine import InvalidTransitionError
from agent_platform.task import Task
from agent_platform.executor import Executor
from agent_platform.planner import Step, TemplatePlanner
from agent_platform.tool_runner import ToolRunner


def test_execution_identity_stable():
    rt = ExecutionRuntime()
    rec = rt.create(task_id="t1", session_id="sess-1", agent_id="agent-a")
    assert rec.execution_id.startswith("exec-")
    assert rec.task_id == "t1"
    assert rec.session_id == "sess-1"
    assert rec.agent_id == "agent-a"
    assert rt.get(rec.execution_id) is rec


def test_lifecycle_happy_path():
    rt = ExecutionRuntime()
    rec = rt.create(task_id="t2")
    assert rec.status == ExecutionState.QUEUED
    rt.start(rec.execution_id)
    assert rec.status == ExecutionState.RUNNING
    assert rec.started_at is not None
    rt.pause(rec.execution_id)
    assert rec.status == ExecutionState.PAUSED
    rt.resume(rec.execution_id)
    assert rec.status == ExecutionState.RUNNING
    rt.complete(rec.execution_id, result={"ok": True})
    assert rec.status == ExecutionState.SUCCEEDED
    assert rec.is_terminal()
    assert rec.finished_at is not None


def test_lifecycle_failed():
    rt = ExecutionRuntime()
    rec = rt.create(task_id="t3")
    rt.start(rec.execution_id)
    rt.fail(rec.execution_id, "something broke")
    assert rec.status == ExecutionState.FAILED
    assert rec.error == "something broke"


def test_lifecycle_cancel_from_running():
    rt = ExecutionRuntime()
    rec = rt.create(task_id="t4")
    rt.start(rec.execution_id)
    rt.cancel(rec.execution_id)
    assert rec.status == ExecutionState.CANCELLED
    assert rec.cancel_requested


def test_lifecycle_cancel_from_queued():
    rt = ExecutionRuntime()
    rec = rt.create(task_id="t5")
    rt.cancel(rec.execution_id)
    assert rec.status == ExecutionState.CANCELLED


def test_lifecycle_cancel_from_paused():
    rt = ExecutionRuntime()
    rec = rt.create(task_id="t6")
    rt.start(rec.execution_id)
    rt.pause(rec.execution_id)
    rt.cancel(rec.execution_id)
    assert rec.status == ExecutionState.CANCELLED


def test_terminal_transition_rejected():
    rt = ExecutionRuntime()
    rec = rt.create(task_id="t7")
    rt.start(rec.execution_id)
    rt.complete(rec.execution_id)
    with pytest.raises(InvalidTransitionError):
        rec.transition(ExecutionState.RUNNING)


def test_invalid_queued_to_succeeded():
    rt = ExecutionRuntime()
    rec = rt.create(task_id="t8")
    with pytest.raises(InvalidTransitionError):
        rec.transition(ExecutionState.SUCCEEDED)


def test_cancel_on_terminal_is_noop():
    rt = ExecutionRuntime()
    rec = rt.create(task_id="t9")
    rt.start(rec.execution_id)
    rt.complete(rec.execution_id)
    rt.cancel(rec.execution_id)
    assert rec.status == ExecutionState.SUCCEEDED


def test_cancel_request_wins_over_complete():
    rt = ExecutionRuntime()
    rec = rt.create(task_id="t10")
    rt.start(rec.execution_id)
    rec.request_cancel()
    rt.complete(rec.execution_id, result="ignored")
    assert rec.status == ExecutionState.CANCELLED


def test_workspace_explicit_and_reportable():
    ws = make_workspace("ws-demo", path="/bound/project", scope="project:demo", metadata={"label": "demo"})
    rt = ExecutionRuntime()
    rec = rt.create(task_id="t11", workspace=ws)
    d = rec.as_dict()["workspace"]
    assert d["workspace_id"] == "ws-demo"
    assert d["path"] == "/bound/project"
    assert not hasattr(ws, "read_file")
    assert not hasattr(rt, "run_command")


def test_capability_allow_list():
    rt = ExecutionRuntime()
    rec = rt.create(task_id="t12", capabilities=["search", "filesystem.read"])
    rt.check_capability(rec.execution_id, "search")
    with pytest.raises(CapabilityDeniedError):
        rt.check_capability(rec.execution_id, "shell")


def test_empty_allow_list_denies_all():
    rt = ExecutionRuntime()
    rec = rt.create(task_id="t13")
    with pytest.raises(CapabilityDeniedError):
        rt.check_capability(rec.execution_id, "search")


def test_capability_denied_emits_event():
    rt = ExecutionRuntime()
    rec = rt.create(task_id="t14", capabilities=["search"])
    with pytest.raises(CapabilityDeniedError):
        rt.check_capability(rec.execution_id, "deploy")
    types = [e.event_type for e in rt.events.history(execution_id=rec.execution_id)]
    assert ExecutionEventType.CAPABILITY_DENIED.value in types


def test_event_emission_and_correlation():
    seen = []
    emitter = EventEmitter()
    emitter.subscribe(lambda e: seen.append(e))
    rt = ExecutionRuntime(emitter)
    rec = rt.create(task_id="t15", session_id="sess-x", agent_id="ag1")
    rt.start(rec.execution_id)
    rt.complete(rec.execution_id)
    types = [e.event_type for e in seen]
    assert ExecutionEventType.CREATED.value in types
    assert ExecutionEventType.STARTED.value in types
    assert ExecutionEventType.COMPLETED.value in types
    for event in seen:
        assert event.event_id
        assert event.execution_id == rec.execution_id
        assert event.task_id == "t15"
        assert event.session_id == "sess-x"


def test_pause_resume_events():
    rt = ExecutionRuntime()
    rec = rt.create(task_id="t16")
    rt.start(rec.execution_id)
    rt.pause(rec.execution_id)
    rt.resume(rec.execution_id)
    types = [e.event_type for e in rt.events.history(execution_id=rec.execution_id)]
    assert ExecutionEventType.PAUSED.value in types
    assert ExecutionEventType.RESUMED.value in types
    paused = [e for e in rt.events.history(execution_id=rec.execution_id) if e.event_type == ExecutionEventType.PAUSED.value]
    assert paused[0].metadata.get("cooperative") is True


def test_secret_redaction_in_events_and_record():
    emitter = EventEmitter()
    rt = ExecutionRuntime(emitter)
    rec = rt.create(task_id="t17", metadata={"api_key": "SECRET_KEY_VALUE", "note": "safe"})
    emitter.emit(
        "custom",
        execution_id=rec.execution_id,
        task_id=rec.task_id,
        session_id=rec.session_id,
        status=rec.status.value,
        metadata={
            "Authorization": "Bearer abcdefghijklmnop",
            "token": "should-not-leak",
            "nested": {"password": "p@ss"},
            "text": "use Bearer sk-abcdefghijklmnopqrst token",
        },
    )
    dumped = " ".join(str(e.as_dict()) for e in emitter.history())
    assert "SECRET_KEY_VALUE" not in dumped
    assert "should-not-leak" not in dumped
    assert "p@ss" not in dumped
    assert "Bearer abcdefghijklmnop" not in dumped
    assert rec.as_dict()["metadata"]["api_key"] == "***"
    assert rec.as_dict()["metadata"]["note"] == "safe"


def test_secret_redaction_in_error_payload():
    rt = ExecutionRuntime()
    rec = rt.create(task_id="t18")
    rt.start(rec.execution_id)
    rt.fail(rec.execution_id, "auth failed Bearer sk-abcdefghijklmnopqrst xyz")
    assert "sk-abcdefghijklmnopqrst" not in (rec.error or "")


def test_redact_secrets_helper():
    assert redact_secrets({"api_key": "x", "ok": 1}) == {"api_key": "***", "ok": 1}
    assert "sk-" not in str(redact_secrets("prefix sk-abcdefghijklmnopqrst suffix"))


def test_legacy_executor_still_works():
    runner = ToolRunner()
    runner.register("echo", lambda context, previous_output=None, **_: "ok")
    planner = TemplatePlanner()
    planner.register_template("echo_goal", [Step(name="echo", tool="echo")])
    task = Task(name="compat", goal="echo_goal")
    result = Executor(runner).run(task, planner.plan("echo_goal"))
    assert result.success is True
    assert result.output == "ok"


def test_list_executions_filters():
    rt = ExecutionRuntime()
    a = rt.create(task_id="tx", session_id="s1")
    b = rt.create(task_id="tx", session_id="s2")
    c = rt.create(task_id="ty", session_id="s1")
    assert {e.execution_id for e in rt.list_executions(task_id="tx")} == {a.execution_id, b.execution_id}
    assert {e.execution_id for e in rt.list_executions(session_id="s1")} == {a.execution_id, c.execution_id}
