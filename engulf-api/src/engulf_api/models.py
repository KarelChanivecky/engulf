from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CallMode(StrEnum):
    NORMAL = "normal"
    HELP = "help"


class AdditionPlacement(StrEnum):
    PREPEND = "prepend"
    BEFORE_SEPARATOR = "before-separator"
    APPEND = "append"


class OutcomeKind(StrEnum):
    COMPLETED = "completed"
    PREEMPTED = "preempted"
    SPAWN_FAILED = "spawn-failed"
    SIGNALED = "signaled"
    FRAMEWORK_FAILED = "framework-failed"


@dataclass(frozen=True, slots=True)
class CallOutcome:
    kind: OutcomeKind
    exit_code: int
    process_started: bool
    signal: int | None = None
    preempted_by: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BeforeCallEvent:
    binary: str
    wrapper_args: tuple[str, ...]
    mode: CallMode


@dataclass(frozen=True, slots=True)
class AfterCallEvent:
    binary: str
    wrapper_args: tuple[str, ...]
    effective_args: tuple[str, ...]
    mode: CallMode
    outcome: CallOutcome
    duration_seconds: float
