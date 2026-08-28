import threading
import time

import pytest

from agent_platform import ExecutionRuntime, FleetStatus, FleetWorkerPlan, WorkerFleet


def test_parallel_workers_are_bounded_and_aggregated_deterministically():
    runtime = ExecutionRuntime()
    fleet = WorkerFleet(runtime=runtime, max_workers=4, max_concurrent_workers=2)
    active = 0
    peak = 0
    lock = threading.Lock()

    def runner(context, execution):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return context["worker_id"]

    for worker_id in ("b", "a", "c"):
        fleet.register_worker(worker_id, "coder", f"do {worker_id}", runner)

    result = fleet.run("task-28", context={"request": "parallel"})
    assert result.status == "succeeded"
    assert [worker.worker_id for worker in result.workers] == ["a", "b", "c"]
    assert peak <= 2
    assert [worker.result for worker in result.workers] == ["a", "b", "c"]


def test_worker_isolation_and_event_correlation():
    runtime = ExecutionRuntime()
    fleet = WorkerFleet(runtime=runtime, max_workers=2, max_concurrent_workers=2)
    seen = {}

    def runner(context, execution):
        seen[context["worker_id"]] = (execution.execution_id, execution.session_id, dict(context))
        return context["worker_id"]

    fleet.register_worker("one", "research", "research one", runner, capabilities=("search",))
    fleet.register_worker("two", "research", "research two", runner, capabilities=("search",))
    result = fleet.run("task-isolated", context={"shared": "read-only"})

    assert result.status == "succeeded"
    assert seen["one"][0] != seen["two"][0]
    assert seen["one"][1] != seen["two"][1]
    assert seen["one"][2]["worker_id"] == "one"
    assert seen["two"][2]["worker_id"] == "two"
    events = runtime.events.history(task_id="task-isolated")
    assert any(event.event_type == "worker.registered" and event.metadata["worker_id"] == "one" for event in events)
    assert any(event.event_type == "worker.progress" and event.metadata["worker_id"] == "two" for event in events)


def test_partial_failure_does_not_poison_siblings():
    fleet = WorkerFleet(max_workers=3, max_concurrent_workers=3)

    def good(context, execution):
        return "ok"

    def bad(context, execution):
        raise RuntimeError("worker failed")

    fleet.register_worker("good", "coder", "good", good)
    fleet.register_worker("bad", "coder", "bad", bad)
    result = fleet.run("task-failure")

    assert result.status == "completed_with_failures"
    statuses = {worker.worker_id: worker.status for worker in result.workers}
    assert statuses == {"bad": "failed", "good": "succeeded"}


def test_fleet_limit_and_unknown_workers_are_enforced():
    fleet = WorkerFleet(max_workers=1, max_concurrent_workers=1)
    runner = lambda context, execution: None
    fleet.register_worker("only", "coder", "only", runner)
    with pytest.raises(ValueError):
        fleet.register_worker("extra", "coder", "extra", runner)
    with pytest.raises(KeyError):
        fleet.run("task", worker_ids=["missing"])


def test_live_status_is_queryable_while_running_and_cancel_propagates():
    fleet = WorkerFleet(max_workers=2, max_concurrent_workers=2)
    started = threading.Event()
    release = threading.Event()

    def runner(context, execution):
        started.set()
        release.wait(2)
        return "late"

    fleet.register_worker("a", "coder", "wait", runner)
    thread = threading.Thread(target=lambda: fleet.run("cancel-me"))
    thread.start()
    assert started.wait(1)
    snapshot = fleet.status("cancel-me")
    assert snapshot.status == "running"
    assert snapshot.workers[0].status == "running"
    fleet.cancel("cancel-me")
    release.set()
    thread.join(2)
    assert not thread.is_alive()
    final = fleet.status("cancel-me")
    assert final.status == "cancelled"
    assert final.workers[0].status == "cancelled"


def test_fleet_status_is_serializable():
    status = FleetStatus(task_id="t", status="queued", workers=())
    assert status.as_dict() == {"task_id": "t", "status": "queued", "workers": []}
