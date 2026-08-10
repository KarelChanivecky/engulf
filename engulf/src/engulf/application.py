from __future__ import annotations

import os
import sys
import warnings
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from engulf_api import (
    AttributedContribution,
    Goal,
    GoalContract,
    GoalPhase,
    GoalResult,
    Invocation,
    InvocationAPI,
    Plugin,
    RegistrationAPI,
    UnusedContextWarning,
)

from ._dispatch import (
    _HookRunner,
    _PhaseDispatcher,
    _PluginCallbackError,
    _report_plugin_error,
    _require_result,
    _RuntimeGoalSetupAPI,
)
from ._state_platform import is_process_elevated
from .diagnostics import (
    DiagnosticsManager,
    DiagnosticsSession,
    LoggingArgumentError,
    LoggingConfig,
    LogLevelOverrides,
    RuntimeDiagnosticsAPI,
    parse_logging_arguments,
    validate_display_name,
)
from .plugin_api import (
    InvocationContextTable,
    RuntimeGoalAPI,
    RuntimePluginAPI,
)
from .plugin_loader import (
    PluginPolicy,
    application_plugin_entry_point_group,
    discover_plugins,
    goal_plugin_entry_point_group,
    load_directory_plugins,
    normalize_application_id,
    resolve_discovered_plugin_orders,
    resolve_plugin_directory,
    validate_goal_plugins,
    validate_plugin_elevation,
)
from .state import (
    InvocationStateManager,
    StateHomeResolver,
    WorkspaceCleanupFailure,
    WorkspaceRootResolver,
)

FRAMEWORK_ERROR_EXIT = 70


class Application[ResultT]:
    """Managed plugin application that delegates its outcome to one goal."""

    def __init__(
        self,
        application_id: str,
        goal: Goal[ResultT],
        *,
        display_name: str,
        plugin_policy: PluginPolicy | None = None,
        logging_config: LoggingConfig | None = None,
        plugin_dir: str | os.PathLike[str] | None = None,
        discover_installed: bool = True,
        workspace_root_resolver: WorkspaceRootResolver | None = None,
        state_home_resolver: StateHomeResolver | None = None,
    ) -> None:
        if not isinstance(goal, Goal):
            raise TypeError("goal must be a Goal")
        if not isinstance(discover_installed, bool):
            raise TypeError("discover_installed must be a boolean")
        if workspace_root_resolver is not None and not callable(
            workspace_root_resolver
        ):
            raise TypeError("workspace_root_resolver must be callable")
        if state_home_resolver is not None and not callable(state_home_resolver):
            raise TypeError("state_home_resolver must be callable")

        contract = goal.contract
        if not isinstance(contract, GoalContract):
            raise TypeError("goal.contract must be a GoalContract")
        if not issubclass(contract.plugin_type, Plugin):
            raise TypeError("goal contract plugin_type must derive from Plugin")
        policy = PluginPolicy.declared() if plugin_policy is None else plugin_policy
        if not isinstance(policy, PluginPolicy):
            raise TypeError("plugin_policy must be a PluginPolicy")

        self._application_id = normalize_application_id(application_id)
        self._display_name = validate_display_name(display_name)
        self._goal = goal
        self._contract = contract
        self._plugin_policy = policy
        self._plugin_directory = (
            None if plugin_dir is None else resolve_plugin_directory(plugin_dir)
        )
        self._workspace_root_resolver = workspace_root_resolver
        self._state_home_resolver = state_home_resolver

        directory_plugins = (
            ()
            if self._plugin_directory is None
            else load_directory_plugins(self._plugin_directory)
        )
        directory_plugins = validate_goal_plugins(
            directory_plugins,
            contract,
            source=f"plugin directory {self._plugin_directory}",
        )
        discovery = discover_plugins(
            self._application_id,
            contract,
            policy,
            directory_plugins=directory_plugins,
            discover_installed=discover_installed,
        )
        self._missing_policy_ids = discovery.missing_policy_ids

        orders = resolve_discovered_plugin_orders(discovery)
        for item in orders.preprocess:
            if item.goal_requirement != contract.requirement:
                raise TypeError(
                    f"plugin {item.plugin_id!r} has incompatible goal requirement"
                )
        self._elevated = is_process_elevated()
        validate_plugin_elevation(
            orders.preprocess,
            elevated=self._elevated,
        )
        self._preprocess_order = orders.preprocess
        self._postprocess_order = orders.postprocess
        self._plugins = tuple(item.plugin for item in self._preprocess_order)
        self._postprocess_plugins = tuple(
            item.plugin for item in self._postprocess_order
        )
        self._hook_runner = _HookRunner(
            self._preprocess_order,
            self._postprocess_order,
        )
        self._phase_dispatcher = _PhaseDispatcher(
            self._preprocess_order,
            self._postprocess_order,
        )

        config = LoggingConfig() if logging_config is None else logging_config
        if not isinstance(config, LoggingConfig):
            raise TypeError("logging_config must be a LoggingConfig")
        plugin_ids = tuple(item.plugin_id for item in self._preprocess_order)
        self._diagnostics = DiagnosticsManager(
            application_id=self._application_id,
            display_name=self._display_name,
            plugin_ids=plugin_ids,
            config=config,
        )
        self._setup_goal()

    @property
    def application_id(self) -> str:
        return self._application_id

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def goal(self) -> Goal[ResultT]:
        return self._goal

    @property
    def goal_contract(self) -> GoalContract:
        return self._contract

    @property
    def plugin_policy(self) -> PluginPolicy:
        return self._plugin_policy

    @property
    def elevated(self) -> bool:
        return self._elevated

    @property
    def goal_plugin_entry_point_group(self) -> str:
        return goal_plugin_entry_point_group(
            self._contract.goal_id,
            self._contract.api_major,
        )

    @property
    def application_plugin_entry_point_group(self) -> str:
        return application_plugin_entry_point_group(self._application_id)

    @property
    def plugins(self) -> tuple[Plugin, ...]:
        return self._plugins

    @property
    def postprocess_plugins(self) -> tuple[Plugin, ...]:
        return self._postprocess_plugins

    @property
    def plugin_directory(self) -> Path | None:
        return self._plugin_directory

    @property
    def missing_policy_ids(self) -> tuple[str, ...]:
        return self._missing_policy_ids

    def invoke(
        self,
        argv: Sequence[str] | None = None,
        *,
        log_overrides: LogLevelOverrides | None = None,
    ) -> GoalResult[ResultT]:
        programmatic_overrides = self._normalize_overrides(log_overrides)
        if programmatic_overrides is None:
            return GoalResult.framework_failed(error="invalid log overrides")

        try:
            received_args = tuple(sys.argv[1:] if argv is None else argv)
            if any(not isinstance(argument, str) for argument in received_args):
                raise TypeError("all invocation arguments must be strings")
            if any("\0" in argument for argument in received_args):
                raise ValueError("invocation arguments cannot contain NUL characters")
            parsed = parse_logging_arguments(
                received_args,
                display_name=self._display_name,
                plugin_ids=frozenset(item.plugin_id for item in self._preprocess_order),
            )
            cwd = Path.cwd().resolve(strict=True)
            invocation = Invocation(
                parsed.arguments,
                cwd,
                dict(os.environ),
            )
        except (OSError, TypeError, ValueError, LoggingArgumentError) as error:
            with self._diagnostics.session(programmatic_overrides) as diagnostics:
                diagnostics.failure(
                    f"invalid invocation: {error}",
                    phase="configuration",
                    error=error,
                )
            return GoalResult.framework_failed(error=str(error))

        with self._diagnostics.session(
            programmatic_overrides,
            parsed.overrides,
        ) as diagnostics:
            return self._invoke(invocation, diagnostics)

    def run(
        self,
        argv: Sequence[str] | None = None,
        *,
        log_overrides: LogLevelOverrides | None = None,
    ) -> int:
        return self.invoke(argv, log_overrides=log_overrides).exit_code

    def _setup_goal(self) -> None:
        with self._diagnostics.session() as diagnostics:
            for plugin_id in self._missing_policy_ids:
                diagnostics.core.debug(
                    "optional plugin %s is not installed for goal %s v%d",
                    plugin_id,
                    self._contract.goal_id,
                    self._contract.api_major,
                    extra={"engulf_phase": "discovery"},
                )
            plugin_apis = {
                item.plugin_id: RuntimeDiagnosticsAPI(
                    item.plugin_id,
                    diagnostics.plugin_logger(item.plugin_id),
                    elevated=self._elevated,
                )
                for item in self._preprocess_order
            }

            def dispatch(
                phase: GoalPhase[Any, Any, RegistrationAPI, Any],
                event: Any,
            ) -> tuple[AttributedContribution[Any], ...]:
                return self._phase_dispatcher.dispatch_setup(
                    phase,
                    event,
                    plugin_apis,
                    diagnostics,
                )

            api = _RuntimeGoalSetupAPI(
                diagnostics,
                dispatch,
                self._application_id,
                self._display_name,
                tuple(item.plugin_id for item in self._preprocess_order),
                self._elevated,
            )
            try:
                self._goal.setup(api)
            except _PluginCallbackError:
                raise
            except Exception as error:
                diagnostics.failure(
                    f"goal {self._contract.goal_id} failed during setup: {error}",
                    phase="goal.setup",
                    error=error,
                )
                raise
            finally:
                api.close()
                for plugin_api in plugin_apis.values():
                    plugin_api.close()

    def _invoke(
        self,
        invocation: Invocation,
        diagnostics: DiagnosticsSession,
    ) -> GoalResult[ResultT]:
        state_manager = InvocationStateManager(
            application_id=self._application_id,
            invocation=invocation,
            workspace_root_resolver=self._workspace_root_resolver,
            state_home_resolver=self._state_home_resolver,
            environment=invocation.environment,
        )
        context_table = InvocationContextTable()
        plugin_apis = {
            item.plugin_id: RuntimePluginAPI(
                participant_id=item.plugin_id,
                context_reads=item.context_reads,
                context_writes=item.context_writes,
                context_table=context_table,
                state_manager=state_manager,
                diagnostic_logger=diagnostics.plugin_logger(item.plugin_id),
                elevated=self._elevated,
            )
            for item in self._preprocess_order
        }

        def dispatch(
            phase: GoalPhase[Any, Any, InvocationAPI, Any],
            event: Any,
        ) -> tuple[AttributedContribution[Any], ...]:
            return self._phase_dispatcher.dispatch_invocation(
                phase,
                event,
                plugin_apis,
            )

        goal_api = RuntimeGoalAPI(
            participant_id=f"__goal__.{self._contract.goal_id}",
            context_reads=None,
            context_writes=None,
            context_table=context_table,
            state_manager=state_manager,
            diagnostic_logger=diagnostics.core,
            elevated=self._elevated,
            dispatch=dispatch,
        )
        entered: set[str] = set()
        cleanup_failures: tuple[WorkspaceCleanupFailure, ...] = ()
        result: GoalResult[Any]
        try:
            before_result = self._hook_runner.run_before(
                invocation,
                plugin_apis,
                diagnostics,
                entered,
            )
            if before_result is None:
                goal_api.activate("goal.achieve")
                try:
                    achieved = self._goal.achieve(invocation, goal_api)
                    result = _require_result(achieved, "goal.achieve")
                except _PluginCallbackError as error:
                    _report_plugin_error(diagnostics, error)
                    result = GoalResult.framework_failed(error=str(error.error))
                except Exception as error:  # noqa: BLE001 - goals are app code.
                    diagnostics.failure(
                        f"goal {self._contract.goal_id} failed: {error}",
                        phase="goal.achieve",
                        error=error,
                    )
                    result = GoalResult.framework_failed(error=str(error))
                finally:
                    goal_api.deactivate()
            else:
                result = before_result

            result = self._hook_runner.run_after(
                invocation,
                result,
                plugin_apis,
                diagnostics,
                entered,
            )
        finally:
            cleanup_failures = state_manager.finalize_destructions()
            for failure in cleanup_failures:
                diagnostics.failure(
                    "workspace state cleanup failed for "
                    f"{failure.plugin_id} at {failure.root}: {failure.error}",
                    plugin_id=(
                        failure.plugin_id if failure.plugin_id in plugin_apis else None
                    ),
                    phase="state_cleanup",
                    error=failure.error,
                )
            for api in plugin_apis.values():
                api.close()
            goal_api.close()
            if context_table.unused_ids:
                warnings.warn(
                    "context written but never read: "
                    + ", ".join(context_table.unused_ids),
                    UnusedContextWarning,
                    stacklevel=2,
                )
        if cleanup_failures:
            return GoalResult.framework_failed(error="workspace state cleanup failed")
        return cast(GoalResult[ResultT], result)

    def _normalize_overrides(
        self,
        overrides: LogLevelOverrides | None,
    ) -> LogLevelOverrides | None:
        if overrides is None:
            result = LogLevelOverrides()
        elif isinstance(overrides, LogLevelOverrides):
            result = overrides
        else:
            with self._diagnostics.session() as diagnostics:
                diagnostics.failure(
                    "invalid log overrides: expected LogLevelOverrides",
                    phase="configuration",
                )
            return None
        try:
            self._diagnostics.validate_overrides(result)
        except (TypeError, ValueError) as error:
            with self._diagnostics.session() as diagnostics:
                diagnostics.failure(
                    f"invalid log overrides: {error}",
                    phase="configuration",
                    error=error,
                )
            return None
        return result
