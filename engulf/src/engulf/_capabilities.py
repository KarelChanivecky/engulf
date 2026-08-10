from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from pathlib import Path
from types import TracebackType

from engulf_api import (
    ContextAccessError,
    MissingContextError,
    PluginLogger,
    PluginPhaseError,
    StateScope,
    StateStore,
    WorkspaceState,
)

from .diagnostics import guarded_plugin_logger
from .state import (
    InvocationStateManager,
    RuntimeStateStore,
    RuntimeWorkspaceState,
    _validate_lock_timeout,
)


class InvocationContextTable:
    """Shared, lazily populated context for one application invocation."""

    def __init__(self) -> None:
        self._values: dict[str, object] = {}
        self._written: set[str] = set()
        self._read: set[str] = set()

    def get(self, context_id: str, default: object | None) -> object | None:
        if context_id not in self._values:
            return default
        self._read.add(context_id)
        return self._values[context_id]

    def require(self, context_id: str) -> object:
        if context_id not in self._values:
            raise MissingContextError(f"context has not been written: {context_id}")
        self._read.add(context_id)
        return self._values[context_id]

    def set(self, context_id: str, value: object) -> None:
        self._values[context_id] = value
        self._written.add(context_id)

    @property
    def unused_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._written - self._read))


class _ActivationState:
    """Owns callback activation, closure, and callback-bound logging."""

    def __init__(
        self,
        participant_id: str,
        diagnostic_logger: logging.Logger,
    ) -> None:
        self.participant_id = participant_id
        self._diagnostic_logger = diagnostic_logger
        self._phase: str | None = None
        self._activation_id = 0
        self._closed = False

    @property
    def activation_id(self) -> int:
        return self._activation_id

    @property
    def closed(self) -> bool:
        return self._closed

    def activate(self, phase: str) -> None:
        if self._closed:
            raise PluginPhaseError(
                f"invocation API for {self.participant_id} is closed"
            )
        if self._phase is not None:
            raise PluginPhaseError(
                f"invocation API for {self.participant_id} is already active"
            )
        self._activation_id += 1
        self._phase = phase

    def deactivate(self) -> None:
        if not self._closed:
            self._phase = None

    def close(self) -> None:
        self._phase = None
        self._closed = True

    def require_active(self, operation: str) -> None:
        if self._closed or self._phase is None:
            raise PluginPhaseError(
                f"{operation} is unavailable outside an active invocation callback"
            )

    def require_current(self, activation_id: int, label: str) -> None:
        if activation_id != self._activation_id:
            raise PluginPhaseError(f"{label} belongs to an earlier callback")

    @property
    def logger(self) -> PluginLogger:
        self.require_active("logger")
        activation_id = self._activation_id
        phase = self._phase
        assert phase is not None
        return guarded_plugin_logger(
            self._diagnostic_logger,
            lambda: self._require_logger_activation(activation_id),
            phase,
        )

    def _require_logger_activation(self, activation_id: int) -> None:
        self.require_active("logger")
        self.require_current(activation_id, "participant logger")


class _ContextCapabilities:
    """Enforces one participant's declared context-table access."""

    def __init__(
        self,
        participant_id: str,
        reads: frozenset[str] | None,
        writes: frozenset[str] | None,
        table: InvocationContextTable,
        require_active: Callable[[str], None],
    ) -> None:
        self._participant_id = participant_id
        self._reads = reads
        self._writes = writes
        self._table = table
        self._require_active = require_active

    def get(self, context_id: str, default: object | None) -> object | None:
        self._require_active("get_context")
        self._require_access(context_id, self._reads, "read")
        return self._table.get(context_id, default)

    def require(self, context_id: str) -> object:
        self._require_active("require_context")
        self._require_access(context_id, self._reads, "read")
        return self._table.require(context_id)

    def set(self, context_id: str, value: object) -> None:
        self._require_active("set_context")
        self._require_access(context_id, self._writes, "write")
        self._table.set(context_id, value)

    def _require_access(
        self,
        context_id: str,
        allowed: frozenset[str] | None,
        operation: str,
    ) -> None:
        if not isinstance(context_id, str) or (
            allowed is not None and context_id not in allowed
        ):
            raise ContextAccessError(
                f"participant {self._participant_id} may not {operation} "
                f"context {context_id!r}"
            )


class _StateCapabilities:
    """Creates and caches participant-scoped state handles."""

    def __init__(
        self,
        participant_id: str,
        state_manager: InvocationStateManager,
        require_active: Callable[[str], None],
        transaction_factory: Callable[
            [RuntimeStateStore, float | None], AbstractContextManager[StateStore]
        ],
    ) -> None:
        self._participant_id = participant_id
        self._state_manager = state_manager
        self._require_active = require_active
        self._transaction_factory = transaction_factory
        self._user_state: RuntimeStateStore | None = None
        self._workspace_state: RuntimeWorkspaceState | None = None
        self._known_workspace_states: dict[Path, RuntimeWorkspaceState] = {}

    def state(self, scope: StateScope) -> StateStore:
        self._require_active("state")
        if scope is StateScope.USER:
            if self._user_state is None:
                self._user_state = RuntimeStateStore(
                    self._state_manager.user_backend(self._participant_id),
                    self._require_active,
                    self._transaction_factory,
                )
            return self._user_state
        if scope is StateScope.WORKSPACE:
            if self._workspace_state is None:
                self._workspace_state = RuntimeWorkspaceState(
                    self._state_manager.current_workspace_backend(self._participant_id),
                    self._require_active,
                    self._transaction_factory,
                )
                self._known_workspace_states[self._workspace_state.root] = (
                    self._workspace_state
                )
            return self._workspace_state
        raise ValueError(f"unsupported state scope: {scope!r}")

    def known_workspaces(self) -> tuple[WorkspaceState, ...]:
        self._require_active("known_workspaces")
        states: list[RuntimeWorkspaceState] = []
        for backend in self._state_manager.known_workspace_backends(
            self._participant_id
        ):
            state = self._known_workspace_states.get(backend.root)
            if state is None:
                state = RuntimeWorkspaceState(
                    backend,
                    self._require_active,
                    self._transaction_factory,
                )
                self._known_workspace_states[backend.root] = state
            states.append(state)
        return tuple(states)


class _LockCoordinator:
    """Coordinates callback-bound transactions and named resource leases."""

    def __init__(
        self,
        activation: _ActivationState,
        state_manager: InvocationStateManager,
    ) -> None:
        self._activation = activation
        self._state_manager = state_manager
        self._active_transaction: _TransactionContext | None = None
        self._active_leases: _LeaseContext | None = None

    def transaction(
        self,
        store: RuntimeStateStore,
        timeout: float | None,
    ) -> AbstractContextManager[StateStore]:
        return _TransactionContext(
            self,
            store,
            timeout,
            self._activation.activation_id,
        )

    def lease(
        self,
        name: str,
        *,
        timeout: float | None = None,
    ) -> AbstractContextManager[None]:
        self._activation.require_active("lease")
        return _LeaseContext(
            self,
            (_validate_lease_name(name),),
            _validate_lock_timeout(timeout),
            self._activation.activation_id,
        )

    def leases(
        self,
        names: Iterable[str],
        *,
        timeout: float | None = None,
    ) -> AbstractContextManager[None]:
        self._activation.require_active("leases")
        return _LeaseContext(
            self,
            _validate_lease_names(names),
            _validate_lock_timeout(timeout),
            self._activation.activation_id,
        )

    def release_active(self) -> None:
        first_error: BaseException | None = None
        for context in (self._active_transaction, self._active_leases):
            if context is None:
                continue
            try:
                context.force_release()
            except BaseException as error:  # noqa: BLE001 - release every lock.
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error

    def claim_transaction(self, transaction: _TransactionContext) -> None:
        self._activation.require_active("state.transaction")
        self._activation.require_current(
            transaction.activation_id,
            "state transaction context",
        )
        if self._active_transaction is not None:
            raise RuntimeError(
                "nested or overlapping state transactions are not allowed"
            )
        self._active_transaction = transaction

    def clear_transaction(self, transaction: _TransactionContext) -> None:
        if self._active_transaction is transaction:
            self._active_transaction = None

    def claim_leases(self, leases: _LeaseContext) -> None:
        self._activation.require_active("leases")
        self._activation.require_current(
            leases.activation_id,
            "resource lease context",
        )
        if self._active_transaction is not None:
            raise RuntimeError(
                "resource leases cannot be acquired while a state transaction is active"
            )
        if self._active_leases is not None:
            raise RuntimeError("nested or overlapping resource leases are not allowed")
        self._active_leases = leases

    def clear_leases(self, leases: _LeaseContext) -> None:
        if self._active_leases is leases:
            self._active_leases = None

    def acquire_leases(
        self,
        names: tuple[str, ...],
        timeout: float | None,
    ) -> AbstractContextManager[None]:
        return self._state_manager.resource_leases(names, timeout=timeout)

    @property
    def transaction_active(self) -> bool:
        return self._active_transaction is not None


class _TransactionContext(AbstractContextManager[StateStore]):
    def __init__(
        self,
        coordinator: _LockCoordinator,
        store: RuntimeStateStore,
        timeout: float | None,
        activation_id: int,
    ) -> None:
        self._coordinator = coordinator
        self._store = store
        self._timeout = timeout
        self.activation_id = activation_id
        self._lock_context: AbstractContextManager[None] | None = None
        self._used = False
        self._entered = False

    def __enter__(self) -> StateStore:
        if self._used:
            raise RuntimeError("a state transaction context can be entered only once")
        self._used = True
        self._coordinator.claim_transaction(self)
        lock_context = self._store._transaction_lock(self._timeout)
        self._lock_context = lock_context
        try:
            lock_context.__enter__()
        except BaseException:
            self._lock_context = None
            self._coordinator.clear_transaction(self)
            raise
        self._store._set_transaction_active(True)
        self._entered = True
        return self._store

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return self._release(exc_type, exc_value, traceback)

    def force_release(self) -> None:
        self._release(None, None, None)

    def _release(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if not self._entered:
            return None
        self._entered = False
        self._store._set_transaction_active(False)
        lock_context = self._lock_context
        self._lock_context = None
        try:
            if lock_context is not None:
                return lock_context.__exit__(exc_type, exc_value, traceback)
            return None
        finally:
            self._coordinator.clear_transaction(self)


class _LeaseContext(AbstractContextManager[None]):
    def __init__(
        self,
        coordinator: _LockCoordinator,
        names: tuple[str, ...],
        timeout: float | None,
        activation_id: int,
    ) -> None:
        self._coordinator = coordinator
        self._names = names
        self._timeout = timeout
        self.activation_id = activation_id
        self._lock_context: AbstractContextManager[None] | None = None
        self._used = False
        self._entered = False

    def __enter__(self) -> None:
        if self._used:
            raise RuntimeError("a resource lease context can be entered only once")
        self._used = True
        self._coordinator.claim_leases(self)
        lock_context = self._coordinator.acquire_leases(
            self._names,
            self._timeout,
        )
        self._lock_context = lock_context
        try:
            lock_context.__enter__()
        except BaseException:
            self._lock_context = None
            self._coordinator.clear_leases(self)
            raise
        self._entered = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return self._release(exc_type, exc_value, traceback)

    def force_release(self) -> None:
        self._release(None, None, None)

    def _release(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if not self._entered:
            return None
        if self._coordinator.transaction_active:
            raise RuntimeError(
                "state transactions must exit before their enclosing resource leases"
            )
        self._entered = False
        lock_context = self._lock_context
        self._lock_context = None
        try:
            if lock_context is not None:
                return lock_context.__exit__(exc_type, exc_value, traceback)
            return None
        finally:
            self._coordinator.clear_leases(self)


def _validate_lease_name(name: str) -> str:
    if not isinstance(name, str):
        raise TypeError("resource lease name must be a string")
    if not name or "\0" in name:
        raise ValueError("resource lease name must be nonempty and contain no NUL")
    return name


def _validate_lease_names(names: Iterable[str]) -> tuple[str, ...]:
    if isinstance(names, str):
        raise TypeError("resource lease names must be an iterable, not a string")
    try:
        iterator = iter(names)
    except TypeError as error:
        raise TypeError("resource lease names must be iterable") from error
    return tuple(sorted({_validate_lease_name(name) for name in iterator}))
