import threading
import time

import pytest

from agent_platform import CollaborationHarness, ExecutionState


def test_workers_run_in_parallel_and_results_are_deterministic():
    started = threading.Barrier(2)
    seen = {}

    def worker(context, execution):
        seen[context["worker_id"]] = execution.session_id
        started.wait(timeout=2)
        return context["worker_id"]

    harness = CollaborationHarness(max_concurrent_workers=2)
    harness.register("b", worker)
    harness.register("a", worker)
    result = harness.run("task-1", context={"shared": "value"})

    assert result.status == "succeeded"
    assert [item.worker_id for item in result.workers] == ["a", "b"]
    assert [item.result for item in result.workers] == ["a", "b"]
    assert seen["a"] != seen["b"]


def test_concurrency_limit_is_enforced():
    lock = threading.Lock()
    active = 0
    maximum = 0

    def worker(context, execution):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return context["worker_id"]

    harness = CollaborationHarness(max_concurrent_workers=2)
    for worker_id in ("a", "b", "c", "d"):
        harness.register(worker_id, worker)
    result = harness.run("task-2")

    assert result.status == "succeeded"
    assert maximum <= 2
    assert len(result.workers) == 4


def test_worker_failure_does_not_poison_siblings():
    def ok(context, execution):
        return "ok"

    def bad(context, execution):
        raise RuntimeError("boom")

    harness = CollaborationHarness(max_concurrent_workers=2)
    harness.register("a", bad)
    harness.register("b", ok)
    result = harness.run("task-3")

    assert result.status == "completed_with_failures"
    assert result.workers[0].status == "failed"
    assert result.workers[1].status == "succeeded"


def test_each_worker_gets_an_independent_context_copy():
    def worker(context, execution):
        context["mutated"] = context["worker_id"]
        return context["mutated"]

    harness = CollaborationHarness()
    harness.register("a", worker)
    harness.register("b", worker)
    source = {"original": True}
    result = harness.run("task-4", context=source)

    assert source == {"original": True}
    assert [item.result for item in result.workers] == ["a", "b"]


def test_events_correlate_parent_worker_agent_session_and_execution():
    harness = CollaborationHarness()
    harness.register("worker-a", lambda context, execution: "done", agent_id="agent-a")
    result = harness.run("parent-5")

    events = harness.events.history(task_id="parent-5")
    assert events
    assert all(event.task_id == "parent-5" for event in events)
    execution = result.workers[0]
    worker_events = [event for event in events if event.execution_id == execution.execution_id]
    assert worker_events
    assert all(event.session_id == execution.session_id for event in worker_events)
    assert all(event.agent_id == "agent-a" for event in worker_events if event.agent_id is not None)
    assert any(event.event_type == "worker.registered" for event in worker_events)


def test_cancel_before_worker_start_isolated_and_reported():
    entered = threading.Event()

    def worker(context, execution):
        entered.set()
        while not context["cancellation_requested"]():
            time.sleep(0.005)
        return "late"

    harness = CollaborationHarness(max_concurrent_workers=1)
    harness.register("a", worker)

    # The runner is intentionally cooperative; cancellation is observable,
    # not a preemptive thread kill.
    def run():
        return harness.run("task-6")

    thread_result = []
    thread = threading.Thread(target=lambda: thread_result.append(run()))
    thread.start()
    assert entered.wait(timeout=2)
    harness.cancel("task-6")
    thread.join(timeout=2)

    assert thread_result
    assert thread_result[0].status == "cancelled"
    assert thread_result[0].workers[0].status == "cancelled"


def test_unknown_worker_is_rejected():
    harness = CollaborationHarness()
    with pytest.raises(KeyError):
        harness.run("task-7", worker_ids=["missing"])


def test_invalid_concurrency_is_rejected():
    with pytest.raises(ValueError):
        CollaborationHarness(max_concurrent_workers=0)

    harness = CollaborationHarness()
    harness.register("a", lambda context, execution: None)
    with pytest.raises(ValueError):
        harness.run("task-8", max_concurrent_workers=0)
