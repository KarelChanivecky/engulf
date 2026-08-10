from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from contextlib import AbstractContextManager
from typing import Literal, TypeVar, overload

from .diagnostics import PluginLogger
from .goals import AttributedContribution, GoalPhase
from .state import StateScope, StateStore, WorkspaceState


class DiagnosticsAPI(ABC):
    """Logging capability shared by every managed callback API."""

    @property
    @abstractmethod
    def logger(self) -> PluginLogger:
        """Return the initialized logger for the active callback."""


class RegistrationAPI(DiagnosticsAPI):
    """Capabilities available during one-time goal/plugin registration."""

    @property
    @abstractmethod
    def elevated(self) -> bool:
        """Return whether the application process is currently elevated."""


class InvocationAPI(DiagnosticsAPI):
    """Capabilities available during an active invocation callback."""

    @property
    @abstractmethod
    def elevated(self) -> bool:
        """Return whether the application process is currently elevated."""

    @abstractmethod
    def lease(
        self,
        name: str,
        *,
        timeout: float | None = None,
    ) -> AbstractContextManager[None]:
        """Acquire one application/user-scoped external-resource lease."""

    @abstractmethod
    def leases(
        self,
        names: Iterable[str],
        *,
        timeout: float | None = None,
    ) -> AbstractContextManager[None]:
        """Acquire several external-resource leases in deterministic order."""

    @abstractmethod
    def get_context(
        self, context_id: str, default: object | None = None
    ) -> object | None:
        """Read an allowed context value without requiring it to exist."""

    @abstractmethod
    def require_context(self, context_id: str) -> object:
        """Read an allowed context value or fail if it has not been written."""

    @abstractmethod
    def set_context(self, context_id: str, value: object) -> None:
        """Create or replace an allowed context value."""

    @overload
    def state(self, scope: Literal[StateScope.WORKSPACE]) -> WorkspaceState: ...

    @overload
    def state(self, scope: Literal[StateScope.USER]) -> StateStore: ...

    @abstractmethod
    def state(self, scope: StateScope) -> StateStore:
        """Return this participant's managed store for the selected scope."""

    @abstractmethod
    def known_workspaces(self) -> tuple[WorkspaceState, ...]:
        """Return centrally registered workspaces owned by this participant."""


class BeforeGoalAPI(InvocationAPI):
    """Capabilities available to a plugin before goal execution."""


class AfterGoalAPI(InvocationAPI):
    """Capabilities available to a plugin after goal execution."""


PluginT = TypeVar("PluginT")
EventT = TypeVar("EventT")
ContributionT = TypeVar("ContributionT")


class GoalSetupAPI(RegistrationAPI):
    """Goal setup logger plus typed setup-phase dispatch."""

    @property
    @abstractmethod
    def application_id(self) -> str:
        """Return the normalized application identifier."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Return the application's command-facing display name."""

    @property
    @abstractmethod
    def plugin_ids(self) -> tuple[str, ...]:
        """Return active plugin IDs in preprocessing order."""

    @abstractmethod
    def dispatch(
        self,
        phase: GoalPhase[PluginT, EventT, RegistrationAPI, ContributionT],
        event: EventT,
    ) -> tuple[AttributedContribution[ContributionT], ...]:
        """Call all goal plugins in the phase's declared order."""


class GoalAPI(InvocationAPI):
    """Goal-owned invocation capabilities plus typed plugin dispatch."""

    @abstractmethod
    def dispatch(
        self,
        phase: GoalPhase[PluginT, EventT, InvocationAPI, ContributionT],
        event: EventT,
    ) -> tuple[AttributedContribution[ContributionT], ...]:
        """Call all goal plugins in the phase's declared order."""
