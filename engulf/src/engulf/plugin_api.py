from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from typing import Any, Literal, overload

from engulf_api import (
    AfterGoalAPI,
    AttributedContribution,
    BeforeGoalAPI,
    GoalAPI,
    GoalPhase,
    InvocationAPI,
    PluginLogger,
    StateScope,
    StateStore,
    WorkspaceState,
)

from ._capabilities import (
    InvocationContextTable,
    _ActivationState,
    _ContextCapabilities,
    _LockCoordinator,
    _StateCapabilities,
)
from .state import InvocationStateManager

__all__ = ["InvocationContextTable", "RuntimeGoalAPI", "RuntimePluginAPI"]

type _Dispatch = Callable[
    [GoalPhase[Any, Any, InvocationAPI, Any], Any],
    tuple[AttributedContribution[Any], ...],
]


class RuntimePluginAPI(BeforeGoalAPI, AfterGoalAPI):
    """Participant-specific facade over callback-bound invocation capabilities."""

    def __init__(
        self,
        *,
        participant_id: str,
        context_reads: frozenset[str] | None,
        context_writes: frozenset[str] | None,
        context_table: InvocationContextTable,
        state_manager: InvocationStateManager,
        diagnostic_logger: logging.Logger,
        elevated: bool,
    ) -> None:
        if type(elevated) is not bool:
            raise TypeError("elevated must be a boolean")
        self._elevated = elevated
        self._activation = _ActivationState(participant_id, diagnostic_logger)
        self._locks = _LockCoordinator(self._activation, state_manager)
        self._contexts = _ContextCapabilities(
            participant_id,
            context_reads,
            context_writes,
            context_table,
            self._activation.require_active,
        )
        self._state = _StateCapabilities(
            participant_id,
            state_manager,
            self._activation.require_active,
            self._locks.transaction,
        )

    def activate(self, phase: str) -> None:
        self._activation.activate(phase)

    def deactivate(self) -> None:
        if self._activation.closed:
            return
        try:
            self._locks.release_active()
        finally:
            self._activation.deactivate()

    def close(self) -> None:
        try:
            self._locks.release_active()
        finally:
            self._activation.close()

    @property
    def logger(self) -> PluginLogger:
        return self._activation.logger

    @property
    def elevated(self) -> bool:
        self._activation.require_active("elevated")
        return self._elevated

    def lease(
        self,
        name: str,
        *,
        timeout: float | None = None,
    ) -> AbstractContextManager[None]:
        return self._locks.lease(name, timeout=timeout)

    def leases(
        self,
        names: Iterable[str],
        *,
        timeout: float | None = None,
    ) -> AbstractContextManager[None]:
        return self._locks.leases(names, timeout=timeout)

    def get_context(
        self,
        context_id: str,
        default: object | None = None,
    ) -> object | None:
        return self._contexts.get(context_id, default)

    def require_context(self, context_id: str) -> object:
        return self._contexts.require(context_id)

    def set_context(self, context_id: str, value: object) -> None:
        self._contexts.set(context_id, value)

    @overload
    def state(self, scope: Literal[StateScope.WORKSPACE]) -> WorkspaceState: ...

    @overload
    def state(self, scope: Literal[StateScope.USER]) -> StateStore: ...

    def state(self, scope: StateScope) -> StateStore:
        return self._state.state(scope)

    def known_workspaces(self) -> tuple[WorkspaceState, ...]:
        return self._state.known_workspaces()

    def _require_active(self, operation: str) -> None:
        self._activation.require_active(operation)


class RuntimeGoalAPI(RuntimePluginAPI, GoalAPI):
    """Goal-owned capabilities with access to runtime phase dispatch."""

    def __init__(self, *, dispatch: _Dispatch, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._dispatch = dispatch

    def dispatch(
        self,
        phase: GoalPhase[Any, Any, InvocationAPI, Any],
        event: Any,
    ) -> tuple[AttributedContribution[Any], ...]:
        self._require_active("dispatch")
        if not isinstance(phase, GoalPhase):
            raise TypeError("phase must be a GoalPhase")
        return self._dispatch(phase, event)
