"""
state_machine.py
مدیریت وضعیت‌های چرخه‌ی عمر یک Task.

حالت‌های ممکن:
    PENDING -> PLANNING -> RUNNING -> (RETRYING <-> RUNNING) -> SUCCEEDED | FAILED
    هر حالتی می‌تواند به CANCELLED برود (به‌جز حالت‌های نهایی).
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Set


class TaskState(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


FINAL_STATES: Set[TaskState] = {
    TaskState.SUCCEEDED,
    TaskState.FAILED,
    TaskState.CANCELLED,
}

_ALLOWED_TRANSITIONS: Dict[TaskState, Set[TaskState]] = {
    TaskState.PENDING: {TaskState.PLANNING, TaskState.CANCELLED},
    TaskState.PLANNING: {TaskState.RUNNING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.RUNNING: {
        TaskState.RETRYING,
        TaskState.SUCCEEDED,
        TaskState.FAILED,
        TaskState.CANCELLED,
    },
    TaskState.RETRYING: {TaskState.RUNNING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.SUCCEEDED: set(),
    TaskState.FAILED: set(),
    TaskState.CANCELLED: set(),
}


class InvalidTransitionError(Exception):
    """وقتی گذار غیرمجاز بین دو وضعیت درخواست شود."""


class StateMachine:
    """ماشین حالت ساده برای پیگیری وضعیت یک Task."""

    def __init__(self, initial: TaskState = TaskState.PENDING) -> None:
        self._state = initial
        self._history: list[TaskState] = [initial]

    @property
    def state(self) -> TaskState:
        return self._state

    @property
    def history(self) -> list[TaskState]:
        return list(self._history)

    def is_final(self) -> bool:
        return self._state in FINAL_STATES

    def can_transition(self, target: TaskState) -> bool:
        return target in _ALLOWED_TRANSITIONS.get(self._state, set())

    def transition(self, target: TaskState) -> TaskState:
        if not self.can_transition(target):
            raise InvalidTransitionError(
                f"گذار غیرمجاز: {self._state.value} -> {target.value}"
            )
        self._state = target
        self._history.append(target)
        return self._state
