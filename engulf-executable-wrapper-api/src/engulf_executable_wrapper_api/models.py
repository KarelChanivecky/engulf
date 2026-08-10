from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from engulf_api import validate_exit_code


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

    def __post_init__(self) -> None:
        if not isinstance(self.kind, OutcomeKind):
            raise TypeError("kind must be an OutcomeKind")
        validate_exit_code(self.exit_code)


@dataclass(frozen=True, slots=True)
class BeforeCallEvent:
    binary: str
    wrapper_args: tuple[str, ...]
    mode: CallMode


@dataclass(frozen=True, slots=True)
class PreparedCallEvent:
    binary: str
    wrapper_args: tuple[str, ...]
    effective_args: tuple[str, ...]
    mode: CallMode


@dataclass(frozen=True, slots=True)
class AfterCallEvent:
    binary: str
    wrapper_args: tuple[str, ...]
    effective_args: tuple[str, ...]
    mode: CallMode
    outcome: CallOutcome
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class ArgumentAddition:
    """One atomic argument group contributed during call analysis."""

    args: tuple[str, ...]
    placement: AdditionPlacement = AdditionPlacement.BEFORE_SEPARATOR

    def __post_init__(self) -> None:
        if type(self.args) is not tuple or not self.args:
            raise ValueError("an added argument group must be a nonempty tuple")
        if any(not isinstance(argument, str) for argument in self.args):
            raise TypeError("added arguments must be strings")
        if any("\0" in argument for argument in self.args):
            raise ValueError("added arguments cannot contain NUL characters")
        if not isinstance(self.placement, AdditionPlacement):
            raise TypeError("placement must be an AdditionPlacement")


@dataclass(frozen=True, slots=True)
class CallContribution:
    """Immutable argument edits and optional preemption from one plugin."""

    removals: frozenset[int] = frozenset()
    additions: tuple[ArgumentAddition, ...] = ()
    preempt_exit_code: int | None = None

    def __post_init__(self) -> None:
        if type(self.removals) is not frozenset or any(
            type(index) is not int or index < 0 for index in self.removals
        ):
            raise ValueError("removals must be a frozenset of nonnegative indexes")
        if type(self.additions) is not tuple or any(
            not isinstance(addition, ArgumentAddition) for addition in self.additions
        ):
            raise TypeError("additions must be a tuple of ArgumentAddition values")
        if self.preempt_exit_code is not None:
            validate_exit_code(
                self.preempt_exit_code,
                label="preempt_exit_code",
            )
