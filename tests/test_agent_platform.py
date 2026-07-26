"""
tests/test_agent_platform.py
پوشش تست برای: planner, executor (شامل retry/failure), state machine,
tool runner, agent registry.

اجرا با: pytest tests/test_agent_platform.py -v
"""

import pytest

from agent_platform.agent_registry import AgentConfig, AgentNotFoundError, AgentRegistry
from agent_platform.cli import run_agent
from agent_platform.executor import Executor
from agent_platform.planner import Step, TemplatePlanner, UnknownGoalError
from agent_platform.state_machine import InvalidTransitionError, StateMachine, TaskState
from agent_platform.task import Task
from agent_platform.tool_runner import ToolNotFoundError, ToolRunner


# ---------------------------------------------------------------------------
# ToolRunner
# ---------------------------------------------------------------------------

def test_tool_runner_register_and_run():
    runner = ToolRunner()
    runner.register("double", lambda x, **_: x * 2)
    assert runner.run("double", x=5) == 10
    assert "double" in runner.list_tools()


def test_tool_runner_duplicate_register_raises():
    runner = ToolRunner()
    runner.register("noop", lambda **_: None)
    with pytest.raises(ValueError):
        runner.register("noop", lambda **_: None)


def test_tool_runner_unknown_tool_raises():
    runner = ToolRunner()
    with pytest.raises(ToolNotFoundError):
        runner.run("missing")


# ---------------------------------------------------------------------------
# StateMachine
# ---------------------------------------------------------------------------

def test_state_machine_happy_path():
    sm = StateMachine()
    assert sm.state == TaskState.PENDING
    sm.transition(TaskState.PLANNING)
    sm.transition(TaskState.RUNNING)
    sm.transition(TaskState.SUCCEEDED)
    assert sm.is_final()
    assert sm.history == [
        TaskState.PENDING,
        TaskState.PLANNING,
        TaskState.RUNNING,
        TaskState.SUCCEEDED,
    ]


def test_state_machine_invalid_transition_raises():
    sm = StateMachine()
    with pytest.raises(InvalidTransitionError):
        sm.transition(TaskState.SUCCEEDED)  # نمی‌توان از PENDING مستقیم به SUCCEEDED رفت


def test_state_machine_retry_cycle():
    sm = StateMachine()
    sm.transition(TaskState.PLANNING)
    sm.transition(TaskState.RUNNING)
    sm.transition(TaskState.RETRYING)
    sm.transition(TaskState.RUNNING)
    sm.transition(TaskState.SUCCEEDED)
    assert sm.state == TaskState.SUCCEEDED


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

def test_template_planner_plan_returns_steps():
    planner = TemplatePlanner()
    planner.register_template(
        "greet",
        [Step(name="say_hi", tool="say_hi", args={"who": "world"})],
    )
    steps = planner.plan("greet")
    assert len(steps) == 1
    assert steps[0].tool == "say_hi"


def test_template_planner_unknown_goal_raises():
    planner = TemplatePlanner()
    with pytest.raises(UnknownGoalError):
        planner.plan("does_not_exist")


def test_template_planner_returns_independent_copies():
    planner = TemplatePlanner()
    planner.register_template("greet", [Step(name="say_hi", tool="say_hi")])
    steps_a = planner.plan("greet")
    steps_b = planner.plan("greet")
    steps_a[0].args["extra"] = "x"
    assert "extra" not in steps_b[0].args


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

def test_executor_runs_successful_pipeline():
    runner = ToolRunner()
    runner.register("upper", lambda context, previous_output=None, **_: "HELLO")
    runner.register("exclaim", lambda context, previous_output=None, **_: f"{previous_output}!")

    steps = [
        Step(name="upper", tool="upper"),
        Step(name="exclaim", tool="exclaim"),
    ]
    task = Task(name="greet_task", goal="greet")
    result = Executor(runner).run(task, steps)

    assert result.success is True
    assert result.output == "HELLO!"
    assert len(result.step_results) == 2
    assert all(r.success for r in result.step_results)


def test_executor_retries_then_succeeds():
    attempts = {"count": 0}

    def flaky(context, previous_output=None, **_):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("موقتاً خراب است")
        return "ok"

    runner = ToolRunner()
    runner.register("flaky", flaky)

    steps = [Step(name="flaky", tool="flaky", max_retries=3)]
    task = Task(name="retry_task", goal="retry_goal")
    result = Executor(runner).run(task, steps)

    assert result.success is True
    assert result.output == "ok"
    assert result.step_results[0].attempts == 3


def test_executor_stops_on_unrecoverable_failure():
    def always_fails(context, previous_output=None, **_):
        raise RuntimeError("خطای دائمی")

    runner = ToolRunner()
    runner.register("bad", always_fails)
    runner.register("never_reached", lambda **_: "should not run")

    steps = [
        Step(name="bad", tool="bad", max_retries=1),
        Step(name="never_reached", tool="never_reached"),
    ]
    task = Task(name="fail_task", goal="fail_goal")
    result = Executor(runner).run(task, steps)

    assert result.success is False
    assert len(result.step_results) == 1  # step دوم اصلاً اجرا نشد
    assert result.step_results[0].attempts == 2  # تلاش اول + یک retry


def test_executor_validator_failure_counts_as_step_failure():
    runner = ToolRunner()
    runner.register("bad_output", lambda context, previous_output=None, **_: -1)

    steps = [
        Step(
            name="bad_output",
            tool="bad_output",
            validator=lambda out: out > 0,
        )
    ]
    task = Task(name="validate_task", goal="validate_goal")
    result = Executor(runner).run(task, steps)

    assert result.success is False
    assert "اعتبارسنجی" in result.error


# ---------------------------------------------------------------------------
# AgentRegistry
# ---------------------------------------------------------------------------

def test_agent_registry_register_and_get():
    registry = AgentRegistry()
    registry.register(AgentConfig(name="news_bot", goal="read_translate_publish"))
    config = registry.get("news_bot")
    assert config.goal == "read_translate_publish"


def test_agent_registry_unknown_agent_raises():
    registry = AgentRegistry()
    with pytest.raises(AgentNotFoundError):
        registry.get("missing_agent")


def test_agent_registry_from_dict():
    registry = AgentRegistry.from_dict(
        {"news_bot": {"goal": "read_translate_publish", "description": "خبر"}}
    )
    assert registry.get("news_bot").description == "خبر"


# ---------------------------------------------------------------------------
# End-to-end: cli.run_agent
# ---------------------------------------------------------------------------

def test_run_agent_end_to_end():
    tool_runner = ToolRunner()
    tool_runner.register("fetch", lambda context, previous_output=None, **_: "raw-news")
    tool_runner.register(
        "translate", lambda context, previous_output=None, **_: f"translated({previous_output})"
    )

    planner = TemplatePlanner()
    planner.register_template(
        "read_translate",
        [
            Step(name="fetch", tool="fetch"),
            Step(name="translate", tool="translate"),
        ],
    )

    agent_registry = AgentRegistry()
    agent_registry.register(AgentConfig(name="news_bot", goal="read_translate"))

    result = run_agent("news_bot", agent_registry, planner, tool_runner)

    assert result.success is True
    assert result.output == "translated(raw-news)"
