from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from engulf_api import (
    AttributedContribution,
    GoalPhase,
    GoalResult,
    GoalResultStatus,
    GoalSetupAPI,
    Invocation,
    InvocationAPI,
    PluginLogger,
    PluginOrder,
    RegistrationAPI,
)

from .diagnostics import (
    DiagnosticsSession,
    RuntimeDiagnosticsAPI,
    guarded_plugin_logger,
)
from .plugin_api import RuntimePluginAPI
from .plugin_loader import LoadedPlugin

type _SetupDispatch = Callable[
    [GoalPhase[Any, Any, RegistrationAPI, Any], Any],
    tuple[AttributedContribution[Any], ...],
]


class _PluginCallbackError(RuntimeError):
    def __init__(self, plugin_id: str, phase: str, error: Exception) -> None:
        super().__init__(f"plugin {plugin_id} failed in {phase}: {error}")
        self.plugin_id = plugin_id
        self.phase = phase
        self.error = error


class _RuntimeGoalSetupAPI(GoalSetupAPI):
    def __init__(
        self,
        diagnostics: DiagnosticsSession,
        dispatch: _SetupDispatch,
        application_id: str,
        display_name: str,
        plugin_ids: tuple[str, ...],
        elevated: bool,
    ) -> None:
        if type(elevated) is not bool:
            raise TypeError("elevated must be a boolean")
        self._diagnostics = diagnostics
        self._dispatch = dispatch
        self._application_id = application_id
        self._display_name = display_name
        self._plugin_ids = plugin_ids
        self._elevated = elevated
        self._active = True

    @property
    def logger(self) -> PluginLogger:
        if not self._active:
            raise RuntimeError("goal setup API is closed")
        return guarded_plugin_logger(
            self._diagnostics.core,
            self._require_active,
            "goal.setup",
        )

    @property
    def elevated(self) -> bool:
        self._require_active()
        return self._elevated

    @property
    def application_id(self) -> str:
        return self._application_id

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def plugin_ids(self) -> tuple[str, ...]:
        return self._plugin_ids

    def dispatch(
        self,
        phase: GoalPhase[Any, Any, RegistrationAPI, Any],
        event: Any,
    ) -> tuple[AttributedContribution[Any], ...]:
        self._require_active()
        if not isinstance(phase, GoalPhase):
            raise TypeError("phase must be a GoalPhase")
        return self._dispatch(phase, event)

    def close(self) -> None:
        self._active = False

    def _require_active(self) -> None:
        if not self._active:
            raise RuntimeError("goal setup API is closed")


class _HookRunner:
    """Runs the outer plugin lifecycle around one goal invocation."""

    def __init__(
        self,
        preprocess_order: tuple[LoadedPlugin, ...],
        postprocess_order: tuple[LoadedPlugin, ...],
    ) -> None:
        self._preprocess_order = preprocess_order
        self._postprocess_order = postprocess_order

    def run_before(
        self,
        invocation: Invocation,
        apis: dict[str, RuntimePluginAPI],
        diagnostics: DiagnosticsSession,
        entered: set[str],
    ) -> GoalResult[Any] | None:
        for item in self._preprocess_order:
            api = apis[item.plugin_id]
            api.activate("before_goal")
            try:
                candidate = item.endpoint.before_goal(invocation, api)
                if candidate is not None:
                    result = _require_result(candidate, "before_goal")
            except Exception as error:  # noqa: BLE001 - isolate extension failures.
                _report_plugin_error(
                    diagnostics,
                    _PluginCallbackError(item.plugin_id, "before_goal", error),
                )
                return GoalResult.framework_failed(error=str(error))
            finally:
                api.deactivate()
            entered.add(item.plugin_id)
            if candidate is None:
                continue
            if (
                result.status is GoalResultStatus.REJECTED
                and result.rejected_by is None
            ):
                result = replace(result, rejected_by=item.plugin_id)
            return result
        return None

    def run_after(
        self,
        invocation: Invocation,
        result: GoalResult[Any],
        apis: dict[str, RuntimePluginAPI],
        diagnostics: DiagnosticsSession,
        entered: set[str],
    ) -> GoalResult[Any]:
        current = result
        for item in self._postprocess_order:
            if item.plugin_id not in entered:
                continue
            api = apis[item.plugin_id]
            api.activate("after_goal")
            try:
                candidate = item.endpoint.after_goal(invocation, current, api)
                current = _require_result(candidate, "after_goal")
            except Exception as error:  # noqa: BLE001 - isolate extension failures.
                _report_plugin_error(
                    diagnostics,
                    _PluginCallbackError(item.plugin_id, "after_goal", error),
                )
                return GoalResult.framework_failed(error=str(error))
            finally:
                api.deactivate()
        return current


class _PhaseDispatcher:
    """Dispatches goal-defined phases through one of the resolved plugin orders."""

    def __init__(
        self,
        preprocess_order: tuple[LoadedPlugin, ...],
        postprocess_order: tuple[LoadedPlugin, ...],
    ) -> None:
        self._preprocess_order = preprocess_order
        self._postprocess_order = postprocess_order

    def dispatch_setup(
        self,
        phase: GoalPhase[Any, Any, RegistrationAPI, Any],
        event: Any,
        apis: dict[str, RuntimeDiagnosticsAPI],
        diagnostics: DiagnosticsSession,
    ) -> tuple[AttributedContribution[Any], ...]:
        contributions: list[AttributedContribution[Any]] = []
        for item in self._order_for(phase.order):
            api = apis[item.plugin_id]
            api.activate(phase.phase_id)
            try:
                value = item.endpoint.dispatch_phase(phase, event, api)
                _append_contribution(phase, item, value, contributions)
            except Exception as error:
                callback_error = _PluginCallbackError(
                    item.plugin_id,
                    phase.phase_id,
                    error,
                )
                _report_plugin_error(diagnostics, callback_error)
                raise callback_error from error
            finally:
                api.deactivate()
        return tuple(contributions)

    def dispatch_invocation(
        self,
        phase: GoalPhase[Any, Any, InvocationAPI, Any],
        event: Any,
        apis: dict[str, RuntimePluginAPI],
    ) -> tuple[AttributedContribution[Any], ...]:
        contributions: list[AttributedContribution[Any]] = []
        for item in self._order_for(phase.order):
            api = apis[item.plugin_id]
            api.activate(phase.phase_id)
            try:
                value = item.endpoint.dispatch_phase(phase, event, api)
                _append_contribution(phase, item, value, contributions)
            except Exception as error:
                raise _PluginCallbackError(
                    item.plugin_id,
                    phase.phase_id,
                    error,
                ) from error
            finally:
                api.deactivate()
        return tuple(contributions)

    def _order_for(self, order: PluginOrder) -> tuple[LoadedPlugin, ...]:
        if order is PluginOrder.PREPROCESS:
            return self._preprocess_order
        if order is PluginOrder.POSTPROCESS:
            return self._postprocess_order
        raise TypeError("phase order must be a PluginOrder")


def _append_contribution(
    phase: GoalPhase[Any, Any, Any, Any],
    item: LoadedPlugin,
    value: Any,
    contributions: list[AttributedContribution[Any]],
) -> None:
    if value is None:
        return
    if phase.contribution_type is not None and not isinstance(
        value,
        phase.contribution_type,
    ):
        raise TypeError(
            f"plugin {item.plugin_id} returned {type(value).__name__} from "
            f"{phase.phase_id}; expected {phase.contribution_type.__name__}"
        )
    contributions.append(AttributedContribution(plugin_id=item.plugin_id, value=value))


def _require_result(value: object, phase: str) -> GoalResult[Any]:
    if not isinstance(value, GoalResult):
        raise TypeError(f"{phase} must return a GoalResult")
    return value


def _report_plugin_error(
    diagnostics: DiagnosticsSession,
    error: _PluginCallbackError,
) -> None:
    diagnostics.failure(
        str(error),
        plugin_id=error.plugin_id,
        phase=error.phase,
        error=error.error,
    )
