"""Issue #33 — persistent jobs, scheduling, retry, recovery."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from agent_platform.execution import ExecutionRuntime, ExecutionState
from agent_platform.jobs import (
    InMemoryJobStore,
    JobRecord,
    JobScheduler,
    JobState,
    JsonFileJobStore,
    RetryPolicy,
    ScheduleSpec,
)
from agent_platform.persistence import InMemoryExecutionStore, JsonFileExecutionStore
from agent_platform.state_machine import InvalidTransitionError


def _sched(tmp_path: Path | None = None) -> JobScheduler:
    if tmp_path is None:
        rt = ExecutionRuntime(store=InMemoryExecutionStore())
        return JobScheduler(rt, store=InMemoryJobStore())
    rt = ExecutionRuntime(store=JsonFileExecutionStore(tmp_path / "exec"))
    return JobScheduler(rt, store=JsonFileJobStore(tmp_path / "jobs"))


def test_create_job_immediate():
    sched = _sched()
    job = sched.create_job(task_id="t1", run_immediately=True)
    assert job.status == JobState.RUNNING
    assert job.execution_id is not None
    assert job.attempt == 1
    rec = sched.runtime.get(job.execution_id)
    assert rec is not None
    assert rec.status == ExecutionState.RUNNING
    assert rec.metadata.get("job_id") == job.job_id


def test_create_job_queued_then_tick():
    sched = _sched()
    job = sched.create_job(
        task_id="t2",
        schedule=ScheduleSpec(immediate=False),
        run_immediately=False,
    )
    assert job.status == JobState.QUEUED
    assert job.execution_id is None
    started = sched.tick(job_id=job.job_id, force=True)
    assert started is not None
    assert started.status == JobState.RUNNING
    assert started.execution_id is not None


def test_delayed_schedule():
    sched = _sched()
    future = time.time() + 3600
    job = sched.create_job(
        task_id="t3",
        schedule=ScheduleSpec(run_at=future, immediate=False),
        run_immediately=False,
    )
    assert job.status == JobState.SCHEDULED
    assert job.next_run_at == future
    # Not due yet
    assert sched.tick(job_id=job.job_id) is None
    assert sched.get(job.job_id).status == JobState.SCHEDULED
    # Force due
    started = sched.tick(job_id=job.job_id, force=True)
    assert started.status == JobState.RUNNING


def test_no_duplicate_execution_after_tick():
    sched = _sched()
    job = sched.create_job(task_id="t4", run_immediately=True)
    eid = job.execution_id
    # Second tick must not create another execution
    sched.tick(job_id=job.job_id, force=True)
    job2 = sched.get(job.job_id)
    assert job2.execution_id == eid
    assert job2.attempt == 1


def test_success_terminal():
    sched = _sched()
    job = sched.create_job(task_id="t5", run_immediately=True)
    sched.runtime.complete(job.execution_id, result={"ok": True})
    updated = sched.on_execution_terminal(job.execution_id, success=True)
    assert updated.status == JobState.SUCCEEDED
    assert updated.is_terminal()


def test_failure_with_retry():
    sched = _sched()
    job = sched.create_job(
        task_id="t6",
        retry=RetryPolicy(max_attempts=3, backoff_seconds=0.0),
        run_immediately=True,
    )
    eid1 = job.execution_id
    sched.runtime.fail(eid1, "boom")
    updated = sched.on_execution_terminal(eid1, success=False, error="boom")
    assert updated.status == JobState.SCHEDULED
    assert updated.attempt == 1
    assert updated.last_error == "boom"
    assert updated.execution_id is None
    # Tick again -> new execution
    started = sched.tick(job_id=job.job_id, force=True)
    assert started.attempt == 2
    assert started.execution_id != eid1
    assert started.status == JobState.RUNNING


def test_retry_exhausted_fails():
    sched = _sched()
    job = sched.create_job(
        task_id="t7",
        retry=RetryPolicy(max_attempts=1),
        run_immediately=True,
    )
    eid = job.execution_id
    sched.runtime.fail(eid, "fatal")
    updated = sched.on_execution_terminal(eid, success=False, error="fatal")
    assert updated.status == JobState.FAILED
    assert updated.last_error == "fatal"
    assert updated.attempt == 1


def test_cancel_job():
    sched = _sched()
    job = sched.create_job(task_id="t8", run_immediately=True)
    cancelled = sched.cancel(job.job_id)
    assert cancelled.status == JobState.CANCELLED
    rec = sched.runtime.get(job.execution_id)
    assert rec.status == ExecutionState.CANCELLED


def test_pause_resume_job():
    sched = _sched()
    job = sched.create_job(task_id="t9", run_immediately=True)
    paused = sched.pause(job.job_id)
    assert paused.status == JobState.PAUSED
    rec = sched.runtime.get(job.execution_id)
    assert rec.status == ExecutionState.PAUSED
    resumed = sched.resume(job.job_id)
    assert resumed.status == JobState.RUNNING
    rec2 = sched.runtime.get(job.execution_id)
    assert rec2.status == ExecutionState.RUNNING


def test_restart_recovery_no_duplicate(tmp_path: Path):
    store_root = tmp_path
    sched1 = _sched(store_root)
    job = sched1.create_job(task_id="t10", run_immediately=True)
    eid = job.execution_id
    jid = job.job_id
    # Simulate process restart
    sched2 = _sched(store_root)
    recovered = sched2.recover_all()
    assert any(j.job_id == jid for j in recovered)
    got = sched2.get(jid)
    assert got is not None
    assert got.execution_id == eid
    assert got.status == JobState.RUNNING
    # Tick must not create a second execution
    sched2.tick(job_id=jid, force=True)
    assert sched2.get(jid).execution_id == eid
    assert sched2.get(jid).attempt == 1


def test_recover_preserves_schedule_and_retry(tmp_path: Path):
    sched1 = _sched(tmp_path)
    future = time.time() + 1000
    job = sched1.create_job(
        task_id="t11",
        schedule=ScheduleSpec(run_at=future, immediate=False),
        retry=RetryPolicy(max_attempts=5, backoff_seconds=1.0),
        metadata={"k": "v"},
        run_immediately=False,
    )
    jid = job.job_id
    sched2 = _sched(tmp_path)
    got = sched2.recover(jid)
    assert got.status == JobState.SCHEDULED
    assert got.next_run_at == future
    assert got.retry.max_attempts == 5
    assert got.metadata["k"] == "v"
    assert got.task_id == "t11"


def test_recurring_job():
    sched = _sched()
    job = sched.create_job(
        task_id="t12",
        schedule=ScheduleSpec(immediate=True, interval_seconds=60.0),
        run_immediately=True,
    )
    eid1 = job.execution_id
    sched.runtime.complete(eid1)
    updated = sched.on_execution_terminal(eid1, success=True)
    assert updated.status == JobState.SCHEDULED
    assert updated.next_run_at is not None
    assert updated.execution_id is None
    # Force next run
    started = sched.tick(job_id=job.job_id, force=True)
    assert started.status == JobState.RUNNING
    assert started.execution_id != eid1
    assert started.attempt == 2


def test_concurrent_jobs():
    sched = _sched()
    jobs = [
        sched.create_job(task_id=f"tc-{i}", run_immediately=True)
        for i in range(5)
    ]
    assert len({j.job_id for j in jobs}) == 5
    assert len({j.execution_id for j in jobs}) == 5
    for j in jobs:
        assert j.status == JobState.RUNNING


def test_corrupted_snapshot_skipped(tmp_path: Path):
    store = JsonFileJobStore(tmp_path / "jobs")
    # Write garbage
    bad = tmp_path / "jobs" / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    # Valid job
    rt = ExecutionRuntime(store=JsonFileExecutionStore(tmp_path / "exec"))
    sched = JobScheduler(rt, store=store)
    job = sched.create_job(task_id="ok", run_immediately=False)
    recovered = sched.recover_all()
    ids = [j.job_id for j in recovered]
    assert job.job_id in ids
    # Corrupted file without job_id key is ignored by list_ids / recover_all


def test_failed_job_diagnostics():
    sched = _sched()
    job = sched.create_job(
        task_id="t13",
        retry=RetryPolicy(max_attempts=1),
        run_immediately=True,
    )
    sched.runtime.fail(job.execution_id, "detailed error message")
    updated = sched.on_execution_terminal(
        job.execution_id, success=False, error="detailed error message"
    )
    assert updated.status == JobState.FAILED
    assert "detailed error message" in (updated.last_error or "")
    d = updated.as_dict()
    assert d["last_error"] == "detailed error message"
    assert d["attempt"] == 1


def test_secret_redaction_in_job_snapshot(tmp_path: Path):
    sched = _sched(tmp_path)
    job = sched.create_job(
        task_id="t14",
        metadata={"api_key": "sk-secret123456789", "note": "ok"},
        run_immediately=False,
    )
    payload = JsonFileJobStore(tmp_path / "jobs").load(job.job_id)
    assert payload is not None
    assert payload["metadata"]["api_key"] == "***"
    assert payload["metadata"]["note"] == "ok"


def test_terminal_cannot_pause_or_resume():
    sched = _sched()
    job = sched.create_job(task_id="t15", run_immediately=True)
    sched.runtime.complete(job.execution_id)
    sched.on_execution_terminal(job.execution_id, success=True)
    with pytest.raises(InvalidTransitionError):
        sched.pause(job.job_id)
    with pytest.raises(InvalidTransitionError):
        sched.resume(job.job_id)


def test_idempotent_job_id_rejection():
    sched = _sched()
    job = sched.create_job(task_id="t16", job_id="fixed-id", run_immediately=False)
    with pytest.raises(ValueError, match="already exists"):
        sched.create_job(task_id="t16b", job_id="fixed-id", run_immediately=False)


def test_list_jobs_filter():
    sched = _sched()
    a = sched.create_job(task_id="ta", run_immediately=False)
    b = sched.create_job(task_id="tb", run_immediately=True)
    assert len(sched.list_jobs(task_id="ta")) == 1
    assert len(sched.list_jobs(status=JobState.RUNNING)) >= 1
    assert sched.get(a.job_id).task_id == "ta"


def test_checkpoint_on_job():
    sched = _sched()
    job = sched.create_job(task_id="t17", run_immediately=True)
    sched.save_checkpoint(job.job_id, {"step": 1})
    sched.save_checkpoint(job.job_id, {"cursor": "x"}, merge=True)
    got = sched.get(job.job_id)
    assert got.checkpoint == {"step": 1, "cursor": "x"}


def test_events_emitted():
    sched = _sched()
    events = []
    sched.runtime.events.subscribe(lambda e: events.append(e))
    job = sched.create_job(task_id="t18", run_immediately=True)
    types = [e.event_type for e in events]
    assert "job.created" in types
    assert "job.started" in types
    assert any("job_id" in (e.metadata or {}) for e in events)


def test_backward_compatible_runtime_without_scheduler():
    """Core ExecutionRuntime still works with no JobScheduler."""
    rt = ExecutionRuntime()
    rec = rt.create(task_id="solo")
    rt.start(rec.execution_id)
    rt.complete(rec.execution_id, 42)
    assert rt.get(rec.execution_id).status == ExecutionState.SUCCEEDED
