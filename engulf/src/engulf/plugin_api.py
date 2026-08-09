from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from engulf_api import (
    AdditionPlacement,
    ContextAccessError,
    MissingContextError,
    PluginAPI,
    PluginPhaseError,
)


@dataclass(frozen=True, slots=True)
class Addition:
    args: tuple[str, ...]
    placement: AdditionPlacement


@dataclass(frozen=True, slots=True)
class PluginContribution:
    removals: frozenset[int]
    additions: tuple[Addition, ...]
    preemption: int | None


class _HookPhase(Enum):
    INACTIVE = auto()
    PREPROCESS = auto()
    POSTPROCESS = auto()
    CLOSED = auto()


class CallContextTable:
    """Shared, lazily populated context for one wrapped call."""

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


class RuntimePluginAPI(PluginAPI):
    """Plugin-specific capability view over one call's shared state."""

    def __init__(
        self,
        *,
        plugin_id: str,
        argument_count: int,
        context_reads: frozenset[str],
        context_writes: frozenset[str],
        context_table: CallContextTable,
    ) -> None:
        self._plugin_id = plugin_id
        self._argument_count = argument_count
        self._context_reads = context_reads
        self._context_writes = context_writes
        self._context_table = context_table
        self._phase = _HookPhase.INACTIVE
        self._removals: set[int] = set()
        self._additions: list[Addition] = []
        self._preemption: int | None = None

    def activate_preprocess(self) -> None:
        self._activate(_HookPhase.PREPROCESS)

    def activate_postprocess(self) -> None:
        self._activate(_HookPhase.POSTPROCESS)

    def deactivate(self) -> None:
        if self._phase is not _HookPhase.CLOSED:
            self._phase = _HookPhase.INACTIVE

    def close(self) -> None:
        self._phase = _HookPhase.CLOSED

    def freeze(self) -> PluginContribution:
        return PluginContribution(
            removals=frozenset(self._removals),
            additions=tuple(self._additions),
            preemption=self._preemption,
        )

    def remove(self, index: int) -> None:
        self._require_preprocess("remove")
        if not isinstance(index, int):
            raise TypeError("argument index must be an integer")
        if index < 0 or index >= self._argument_count:
            raise IndexError(f"argument index {index} is out of range")
        self._removals.add(index)

    def remove_range(self, start: int, stop: int) -> None:
        self._require_preprocess("remove_range")
        if not isinstance(start, int) or not isinstance(stop, int):
            raise TypeError("argument range bounds must be integers")
        if start < 0 or stop < start or stop > self._argument_count:
            raise IndexError(f"argument range [{start}, {stop}) is out of range")
        self._removals.update(range(start, stop))

    def add(
        self,
        *args: str,
        placement: AdditionPlacement = AdditionPlacement.BEFORE_SEPARATOR,
    ) -> None:
        self._require_preprocess("add")
        if not args:
            raise ValueError("an added argument group cannot be empty")
        if any(not isinstance(arg, str) for arg in args):
            raise TypeError("added arguments must be strings")
        if any("\0" in arg for arg in args):
            raise ValueError("arguments cannot contain NUL characters")
        if not isinstance(placement, AdditionPlacement):
            raise TypeError("placement must be an AdditionPlacement")
        self._additions.append(Addition(tuple(args), placement))

    def preempt(self, exit_code: int) -> None:
        self._require_preprocess("preempt")
        if not isinstance(exit_code, int) or isinstance(exit_code, bool):
            raise TypeError("exit code must be an integer")
        if exit_code < 0 or exit_code > 255:
            raise ValueError("exit code must be between 0 and 255")
        if self._preemption is not None:
            raise RuntimeError("a plugin can preempt a call only once")
        self._preemption = exit_code

    def get_context(
        self, context_id: str, default: object | None = None
    ) -> object | None:
        self._require_active("get_context")
        self._require_context_access(context_id, self._context_reads, "read")
        return self._context_table.get(context_id, default)

    def require_context(self, context_id: str) -> object:
        self._require_active("require_context")
        self._require_context_access(context_id, self._context_reads, "read")
        return self._context_table.require(context_id)

    def set_context(self, context_id: str, value: object) -> None:
        self._require_active("set_context")
        self._require_context_access(context_id, self._context_writes, "write")
        self._context_table.set(context_id, value)

    def _activate(self, phase: _HookPhase) -> None:
        if self._phase is _HookPhase.CLOSED:
            raise PluginPhaseError(f"PluginAPI for {self._plugin_id} is closed")
        if self._phase is not _HookPhase.INACTIVE:
            raise PluginPhaseError(f"PluginAPI for {self._plugin_id} is already active")
        self._phase = phase

    def _require_active(self, operation: str) -> None:
        if self._phase not in {_HookPhase.PREPROCESS, _HookPhase.POSTPROCESS}:
            raise PluginPhaseError(
                f"{operation} is unavailable outside an active plugin hook"
            )

    def _require_preprocess(self, operation: str) -> None:
        if self._phase is not _HookPhase.PREPROCESS:
            raise PluginPhaseError(
                f"{operation} is available only during preprocessing"
            )

    def _require_context_access(
        self, context_id: str, allowed: frozenset[str], operation: str
    ) -> None:
        if not isinstance(context_id, str) or context_id not in allowed:
            raise ContextAccessError(
                f"plugin {self._plugin_id} may not {operation} context {context_id!r}"
            )
