from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

from .identifiers import validate_global_identifier
from .validation import validate_exit_code

if TYPE_CHECKING:
    from .plugin_api import GoalAPI, GoalSetupAPI


class GoalResultStatus(StrEnum):
    """Framework-level disposition of one goal invocation."""

    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"
    FRAMEWORK_FAILED = "framework-failed"
    DIAGNOSTIC = "diagnostic"


@dataclass(frozen=True, slots=True)
class GoalResult[ResultT]:
    """Typed result returned by a goal and transformed by outer plugins."""

    status: GoalResultStatus
    exit_code: int
    value: ResultT | None = None
    error: str | None = None
    rejected_by: str | None = None
    diagnostic_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, GoalResultStatus):
            raise TypeError("status must be a GoalResultStatus")
        validate_exit_code(self.exit_code)
        if self.error is not None and not isinstance(self.error, str):
            raise TypeError("error must be a string or None")
        if self.rejected_by is not None:
            validate_global_identifier(self.rejected_by, label="rejected_by")
        if type(self.diagnostic_ids) is not tuple:
            raise TypeError("diagnostic_ids must be a tuple")
        for diagnostic_id in self.diagnostic_ids:
            validate_global_identifier(diagnostic_id, label="diagnostic_id")
        if self.status is not GoalResultStatus.DIAGNOSTIC and self.diagnostic_ids:
            raise ValueError("diagnostic_ids require DIAGNOSTIC status")
        if self.status is GoalResultStatus.DIAGNOSTIC and not self.diagnostic_ids:
            raise ValueError("DIAGNOSTIC status requires diagnostic_ids")
        if len(set(self.diagnostic_ids)) != len(self.diagnostic_ids):
            raise ValueError("diagnostic_ids must be unique")

    @classmethod
    def completed(
        cls,
        value: ResultT | None = None,
        *,
        exit_code: int = 0,
    ) -> GoalResult[ResultT]:
        return cls(GoalResultStatus.COMPLETED, exit_code, value)

    @classmethod
    def rejected(
        cls,
        exit_code: int,
        value: ResultT | None = None,
        *,
        rejected_by: str | None = None,
        error: str | None = None,
    ) -> GoalResult[ResultT]:
        return cls(
            GoalResultStatus.REJECTED,
            exit_code,
            value,
            error,
            rejected_by,
        )

    @classmethod
    def failed(
        cls,
        exit_code: int,
        value: ResultT | None = None,
        *,
        error: str | None = None,
    ) -> GoalResult[ResultT]:
        return cls(GoalResultStatus.FAILED, exit_code, value, error)

    @classmethod
    def framework_failed(
        cls,
        *,
        exit_code: int = 70,
        error: str | None = None,
    ) -> GoalResult[ResultT]:
        return cls(GoalResultStatus.FRAMEWORK_FAILED, exit_code, error=error)

    @classmethod
    def diagnostic(
        cls,
        diagnostic_ids: tuple[str, ...],
        *,
        exit_code: int = 0,
        error: str | None = None,
    ) -> GoalResult[ResultT]:
        return cls(
            GoalResultStatus.DIAGNOSTIC,
            exit_code,
            error=error,
            diagnostic_ids=diagnostic_ids,
        )

    @property
    def contributing_diagnostic_ids(self) -> tuple[str, ...]:
        return self.diagnostic_ids


@dataclass(frozen=True, slots=True)
class Invocation:
    """Goal-neutral inputs and process context for one application invocation."""

    arguments: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str]

    def __post_init__(self) -> None:
        if type(self.arguments) is not tuple or any(
            not isinstance(argument, str) for argument in self.arguments
        ):
            raise TypeError("arguments must be a tuple of strings")
        if any("\0" in argument for argument in self.arguments):
            raise ValueError("arguments cannot contain NUL characters")
        if not isinstance(self.cwd, Path) or not self.cwd.is_absolute():
            raise ValueError("cwd must be an absolute pathlib.Path")
        try:
            environment = dict(self.environment)
        except (TypeError, ValueError) as error:
            raise TypeError("environment must be a string mapping") from error
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in environment.items()
        ):
            raise TypeError("environment must contain only string keys and values")
        object.__setattr__(self, "environment", MappingProxyType(environment))


@dataclass(frozen=True, slots=True)
class GoalRequirement:
    """The goal contract required by one plugin adapter."""

    goal_id: str
    api_major: int

    def __post_init__(self) -> None:
        validate_global_identifier(self.goal_id, label="goal_id")
        if type(self.api_major) is not int or self.api_major < 1:
            raise ValueError("goal API major must be a positive integer")


@dataclass(frozen=True, slots=True)
class GoalContract:
    """Stable goal identity plus the runtime type accepted for its plugins."""

    requirement: GoalRequirement
    plugin_type: type[object]

    def __post_init__(self) -> None:
        if not isinstance(self.requirement, GoalRequirement):
            raise TypeError("requirement must be a GoalRequirement")
        if not isinstance(self.plugin_type, type):
            raise TypeError("plugin_type must be a type")

    @property
    def goal_id(self) -> str:
        return self.requirement.goal_id

    @property
    def api_major(self) -> int:
        return self.requirement.api_major


class PluginOrder(StrEnum):
    """One of the two shared dependency orders used by a goal phase."""

    PREPROCESS = "preprocess"
    POSTPROCESS = "postprocess"


@dataclass(frozen=True, slots=True, kw_only=True)
class GoalPhase[PluginT, EventT, PhaseAPIT, ContributionT]:
    """Typed phase declaration dispatched through a plugin execution endpoint."""

    phase_id: str
    order: PluginOrder
    local_callback: Callable[[PluginT, EventT, PhaseAPIT], ContributionT | None]
    contribution_type: type[ContributionT] | None = None

    def __post_init__(self) -> None:
        validate_global_identifier(self.phase_id, label="phase_id")
        if not isinstance(self.order, PluginOrder):
            raise TypeError("order must be a PluginOrder")
        if not callable(self.local_callback):
            raise TypeError("local_callback must be callable")
        if self.contribution_type is not None and not isinstance(
            self.contribution_type, type
        ):
            raise TypeError("contribution_type must be a type or None")


@dataclass(frozen=True, slots=True, kw_only=True)
class AttributedContribution[ContributionT]:
    """One immutable goal-phase contribution and its stable plugin identity."""

    plugin_id: str
    value: ContributionT

    def __post_init__(self) -> None:
        validate_global_identifier(self.plugin_id, label="plugin_id")


class Goal[ResultT](ABC):
    """Application-owned strategy for achieving one invocation outcome."""

    @property
    @abstractmethod
    def contract(self) -> GoalContract:
        """Return the stable contract implemented by this goal."""

    def setup(self, api: GoalSetupAPI) -> None:
        """Perform one-time setup after plugin discovery and validation."""

    def normalize_invocation(self, invocation: Invocation) -> Invocation:
        """Return goal-specific normalized inputs before outer plugin callbacks."""
        return invocation

    @abstractmethod
    def achieve(
        self,
        invocation: Invocation,
        api: GoalAPI,
    ) -> GoalResult[ResultT]:
        """Run the goal-specific process for one invocation."""
