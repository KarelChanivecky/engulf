from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal, overload

from .models import AdditionPlacement
from .state import StateScope, StateStore, WorkspaceState


class PluginAPI(ABC):
    """Call-scoped capabilities supplied to a plugin by Engulf."""

    @abstractmethod
    def remove(self, index: int) -> None:
        """Remove one original argument during preprocessing."""

    @abstractmethod
    def remove_range(self, start: int, stop: int) -> None:
        """Remove a half-open range of original arguments during preprocessing."""

    @abstractmethod
    def add(
        self,
        *args: str,
        placement: AdditionPlacement = AdditionPlacement.BEFORE_SEPARATOR,
    ) -> None:
        """Add one atomic argument group during preprocessing."""

    @abstractmethod
    def preempt(self, exit_code: int) -> None:
        """Request binary preemption during preprocessing."""

    @abstractmethod
    def get_context(
        self, context_id: str, default: object | None = None
    ) -> object | None:
        """Read declared context, returning a default when it is absent."""

    @abstractmethod
    def require_context(self, context_id: str) -> object:
        """Read declared context or raise MissingContextError when absent."""

    @abstractmethod
    def set_context(self, context_id: str, value: object) -> None:
        """Create or overwrite declared context."""

    @overload
    def state(self, scope: Literal[StateScope.WORKSPACE]) -> WorkspaceState: ...

    @overload
    def state(self, scope: Literal[StateScope.USER]) -> StateStore: ...

    @abstractmethod
    def state(self, scope: StateScope) -> StateStore:
        """Return this plugin's store for the selected scope."""

    @abstractmethod
    def known_workspaces(self) -> tuple[WorkspaceState, ...]:
        """Return every centrally registered workspace owned by this plugin."""
