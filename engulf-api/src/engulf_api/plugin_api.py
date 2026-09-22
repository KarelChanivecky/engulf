from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Literal, TypeVar, overload

from .application import ApplicationMetadata
from .diagnostics import PluginLogger
from .goals import AttributedContribution, GoalPhase
from .state import StateScope, StateStore, WorkspaceState


class DiagnosticsAPI(ABC):
    """Application metadata and logging shared by every managed callback API."""

    @property
    @abstractmethod
    def application(self) -> ApplicationMetadata:
        """Return immutable metadata for the active application."""

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
    def set_context(
        self, context_id: str, value: object, *, allow_unused: bool = False
    ) -> None:
        """Create or replace an allowed context value.

        ``allow_unused=True`` suppresses the unread-context warning for this ID.
        The latest write determines this policy; successful reads remain tracked
        per ID for the invocation. The flag must be a boolean.
        """

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

    @property
    @abstractmethod
    def postprocess_plugin_ids(self) -> tuple[str, ...]:
        """Return active plugin IDs in postprocessing order."""

    @property
    def dependency_map(self) -> Mapping[str, tuple[str, ...]]:
        """Return the active hard-dependency closure for manifest compilation."""
        return {}

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
        *,
        plugin_ids: Sequence[str] | None = None,
    ) -> tuple[AttributedContribution[ContributionT], ...]:
        """Call goal plugins in the phase's declared order.

        Pass `plugin_ids` to call exactly those active plugins, in the given
        order, instead of the phase's shared order. Use it for phases that must
        address a subset established earlier in the same invocation, such as
        unwinding the plugins that completed an earlier phase.
        """
