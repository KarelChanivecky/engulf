from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .application import ApplicationMetadata
from .diagnostics import PluginLogger
from .goals import GoalRequirement
from .identifiers import validate_global_identifier
from .plugin import ActivePlugin, PluginMetadata, PluginSource
from .validation import validate_exit_code


@dataclass(frozen=True, slots=True, kw_only=True)
class DiagnosticRequest:
    """Sanitized input supplied to an isolated diagnostic extension."""

    arguments: tuple[str, ...]
    application: ApplicationMetadata
    goal: GoalRequirement

    def __post_init__(self) -> None:
        if type(self.arguments) is not tuple or any(
            not isinstance(argument, str) for argument in self.arguments
        ):
            raise TypeError("diagnostic arguments must be a tuple of strings")
        if any("\0" in argument for argument in self.arguments):
            raise ValueError("diagnostic arguments cannot contain NUL characters")
        if not isinstance(self.application, ApplicationMetadata):
            raise TypeError("application must be ApplicationMetadata")
        if not isinstance(self.goal, GoalRequirement):
            raise TypeError("goal must be GoalRequirement")

    @property
    def application_id(self) -> str:
        return self.application.application_id

    @property
    def goal_id(self) -> str:
        return self.goal.goal_id

    @property
    def goal_api_major(self) -> int:
        return self.goal.api_major


@dataclass(frozen=True, slots=True, kw_only=True)
class DiagnosticExtension:
    """Import-free discovery record for one isolated diagnostic extension.

    ``available`` is ``None`` until the runtime first tests diagnostic isolation.
    """

    diagnostic_id: str
    triggers: tuple[str, ...]
    distribution: str
    version: str
    target: str
    available: bool | None = None
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        validate_global_identifier(self.diagnostic_id, label="diagnostic_id")
        if type(self.triggers) is not tuple or any(
            not isinstance(trigger, str) or not trigger.startswith("--")
            for trigger in self.triggers
        ):
            raise ValueError("diagnostic triggers must be a tuple of -- options")
        if len(set(self.triggers)) != len(self.triggers):
            raise ValueError("diagnostic triggers must be unique")
        for field, value in (
            ("distribution", self.distribution),
            ("version", self.version),
            ("target", self.target),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"diagnostic {field} must be a nonempty string")
        if self.available is not None and type(self.available) is not bool:
            raise TypeError("diagnostic available must be a boolean or None")
        if self.unavailable_reason is not None and (
            not isinstance(self.unavailable_reason, str) or not self.unavailable_reason
        ):
            raise ValueError("unavailable_reason must be a nonempty string or None")
        if self.available is not False and self.unavailable_reason is not None:
            raise ValueError(
                "unavailable_reason requires diagnostic available to be False"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class PluginExecutionRecord:
    """Normal-plugin provenance and one-based execution positions."""

    plugin: ActivePlugin
    preprocess_position: int
    postprocess_position: int

    def __post_init__(self) -> None:
        if not isinstance(self.plugin, ActivePlugin):
            raise TypeError("plugin must be ActivePlugin")
        for field in ("preprocess_position", "postprocess_position"):
            value = getattr(self, field)
            if type(value) is not int or value < 1:
                raise ValueError(f"{field} must be a positive integer")

    @property
    def plugin_id(self) -> str:
        return self.plugin.plugin_id

    @property
    def metadata(self) -> PluginMetadata:
        return self.plugin.metadata

    @property
    def source(self) -> PluginSource:
        return self.plugin.source


@dataclass(frozen=True, slots=True, kw_only=True)
class DiagnosticContribution:
    """The only intended host-visible result of a diagnostic extension."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.stdout, str) or not isinstance(self.stderr, str):
            raise TypeError("diagnostic stdout and stderr must be strings")
        validate_exit_code(self.exit_code)


class DiagnosticAPI(ABC):
    """Read-only data and buffered logging available inside a worker."""

    @property
    @abstractmethod
    def active_plugins(self) -> tuple[ActivePlugin, ...]: ...

    @property
    @abstractmethod
    def plugin_executions(self) -> tuple[PluginExecutionRecord, ...]: ...

    @property
    def normal_plugins(self) -> tuple[PluginExecutionRecord, ...]:
        return self.plugin_executions

    @property
    def plugin_records(self) -> tuple[PluginExecutionRecord, ...]:
        return self.plugin_executions

    @property
    def plugins(self) -> tuple[ActivePlugin, ...]:
        return self.active_plugins

    @property
    @abstractmethod
    def diagnostic_extensions(self) -> tuple[DiagnosticExtension, ...]: ...

    @property
    @abstractmethod
    def elevated(self) -> bool: ...

    @property
    @abstractmethod
    def logger(self) -> PluginLogger: ...


class DiagnosticPlugin(ABC):
    """Base contract for code imported only by an isolated worker."""

    @abstractmethod
    def diagnose(
        self,
        request: DiagnosticRequest,
        api: DiagnosticAPI,
    ) -> DiagnosticContribution:
        """Return a bounded diagnostic response."""
