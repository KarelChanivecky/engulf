from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from engulf_api import (
    ApplicationMetadata,
    AttributedContribution,
    GoalPhase,
    GoalResult,
    GoalResultStatus,
    GoalSetupAPI,
    Invocation,
    InvocationAPI,
    PluginCallbackError,
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


class _RuntimeGoalSetupAPI(GoalSetupAPI):
    def __init__(
        self,
        diagnostics: DiagnosticsSession,
        dispatch: _SetupDispatch,
        application: ApplicationMetadata,
        plugin_ids: tuple[str, ...],
        elevated: bool,
    ) -> None:
        if not isinstance(application, ApplicationMetadata):
            raise TypeError("application must be ApplicationMetadata")
        if type(elevated) is not bool:
            raise TypeError("elevated must be a boolean")
        self._diagnostics = diagnostics
        self._dispatch = dispatch
        self._application = application
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
    def application(self) -> ApplicationMetadata:
        self._require_active()
        return self._application

    @property
    def elevated(self) -> bool:
        self._require_active()
        return self._elevated

    @property
    def application_id(self) -> str:
        return self.application.application_id

    @property
    def display_name(self) -> str:
        return self.application.display_name

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
                    PluginCallbackError(item.plugin_id, "before_goal", error),
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
                    PluginCallbackError(item.plugin_id, "after_goal", error),
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
        return self._dispatch(phase, event, apis, diagnostics)

    def dispatch_invocation(
        self,
        phase: GoalPhase[Any, Any, InvocationAPI, Any],
        event: Any,
        apis: dict[str, RuntimePluginAPI],
        diagnostics: DiagnosticsSession,
        plugin_ids: Sequence[str] | None = None,
    ) -> tuple[AttributedContribution[Any], ...]:
        return self._dispatch(phase, event, apis, diagnostics, plugin_ids)

    def _dispatch(
        self,
        phase: GoalPhase[Any, Any, Any, Any],
        event: Any,
        apis: Mapping[str, Any],
        diagnostics: DiagnosticsSession,
        plugin_ids: Sequence[str] | None = None,
    ) -> tuple[AttributedContribution[Any], ...]:
        """Run one phase, isolating plugin failures only when the phase asks."""
        contributions: list[AttributedContribution[Any]] = []
        completed: list[str] = []
        for item in self._selection(phase, plugin_ids):
            api = apis[item.plugin_id]
            api.activate(phase.phase_id)
            try:
                value = item.endpoint.dispatch_phase(phase, event, api)
                _append_contribution(phase, item, value, contributions)
            except Exception as error:
                callback_error = PluginCallbackError(
                    item.plugin_id,
                    phase.phase_id,
                    error,
                    completed_plugin_ids=tuple(completed),
                )
                _report_plugin_error(diagnostics, callback_error)
                if not phase.isolate_failures:
                    raise callback_error from error
            else:
                completed.append(item.plugin_id)
            finally:
                api.deactivate()
        return tuple(contributions)

    def _selection(
        self,
        phase: GoalPhase[Any, Any, Any, Any],
        plugin_ids: Sequence[str] | None,
    ) -> tuple[LoadedPlugin, ...]:
        order = self._order_for(phase.order)
        if plugin_ids is None:
            return order
        available = {item.plugin_id: item for item in order}
        selection: list[LoadedPlugin] = []
        seen: set[str] = set()
        for plugin_id in plugin_ids:
            item = available.get(plugin_id)
            if item is None:
                raise ValueError(
                    f"{phase.phase_id} cannot dispatch to inactive plugin {plugin_id}"
                )
            if plugin_id in seen:
                raise ValueError(
                    f"{phase.phase_id} cannot dispatch to {plugin_id} twice"
                )
            seen.add(plugin_id)
            selection.append(item)
        return tuple(selection)

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
    error: PluginCallbackError,
) -> None:
    diagnostics.failure(
        str(error),
        plugin_id=error.plugin_id,
        phase=error.phase,
        error=error.error,
    )
