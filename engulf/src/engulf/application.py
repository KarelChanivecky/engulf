from __future__ import annotations

import os
import sys
import threading
import warnings
from collections.abc import Iterable, Sequence
from pathlib import Path
from types import TracebackType
from typing import Any, Self, cast

from engulf_api import (
    ApplicationMetadata,
    AttributedContribution,
    DiagnosticExtension,
    DiagnosticRequest,
    Goal,
    GoalContract,
    GoalPhase,
    GoalResult,
    GoalResultStatus,
    Invocation,
    InvocationAPI,
    Plugin,
    PluginCallbackError,
    PluginExecutionRecord,
    RegistrationAPI,
    UnusedContextWarning,
)

from ._dispatch import (
    _HookRunner,
    _PhaseDispatcher,
    _require_result,
    _RuntimeGoalSetupAPI,
)
from ._state_platform import is_process_elevated
from .diagnostic_extensions import (
    BubblewrapDiagnosticRunner,
    DiagnosticIsolationConfig,
    _DiscoveredDiagnostic,
    diagnostic_entry_point_group,
    diagnostic_trigger_entry_point_group,
    discover_diagnostics,
    matching_diagnostics,
)
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
from .plugin_info import ActivePlugin
from .plugin_loader import (
    EntryPointIndex,
    PluginPolicy,
    PluginRequirementError,
    application_plugin_entry_point_group,
    discover_plugins,
    goal_plugin_entry_point_group,
    load_directory_plugins,
    normalize_application_id,
    normalize_plugin_declaration_application_ids,
    plugin_dependency_entry_point_prefix,
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
        vendor: str,
        product: str,
        short_product_name: str,
        version: str,
        plugin_policy: PluginPolicy | None = None,
        required_plugin_ids: Iterable[str] = (),
        plugin_declaration_application_ids: Iterable[str] = (),
        logging_config: LoggingConfig | None = None,
        plugin_dir: str | os.PathLike[str] | None = None,
        discover_installed: bool = True,
        workspace_root_resolver: WorkspaceRootResolver | None = None,
        state_home_resolver: StateHomeResolver | None = None,
        diagnostic_isolation_config: DiagnosticIsolationConfig | None = None,
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
        required_ids = PluginPolicy.declared(include=required_plugin_ids).plugin_ids
        policy = policy.including(required_ids)

        self._application_id = normalize_application_id(application_id)
        self._display_name = validate_display_name(display_name)
        self._application_metadata = ApplicationMetadata(
            application_id=self._application_id,
            display_name=self._display_name,
            vendor=vendor,
            product=product,
            short_product_name=short_product_name,
            version=version,
        )
        self._goal = goal
        self._contract = contract
        self._plugin_policy = policy
        self._required_plugin_ids = required_ids
        self._plugin_declaration_application_ids = (
            normalize_plugin_declaration_application_ids(
                self._application_id,
                plugin_declaration_application_ids,
            )
        )
        self._plugin_directory = (
            None if plugin_dir is None else resolve_plugin_directory(plugin_dir)
        )
        self._workspace_root_resolver = workspace_root_resolver
        self._state_home_resolver = state_home_resolver
        isolation_config = (
            DiagnosticIsolationConfig()
            if diagnostic_isolation_config is None
            else diagnostic_isolation_config
        )
        if not isinstance(isolation_config, DiagnosticIsolationConfig):
            raise TypeError(
                "diagnostic_isolation_config must be a DiagnosticIsolationConfig"
            )
        self._diagnostic_isolation = isolation_config
        self._lifecycle_lock = threading.Lock()
        self._invocation_active = False
        self._closed = False

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
        entry_point_index: EntryPointIndex | None = None
        if discover_installed:
            declaration_entry_point_groups = tuple(
                application_plugin_entry_point_group(application_id)
                for application_id in self._plugin_declaration_application_ids
            )
            entry_point_index = EntryPointIndex.discover(
                (
                    goal_plugin_entry_point_group(
                        contract.goal_id,
                        contract.api_major,
                    ),
                    *declaration_entry_point_groups,
                    diagnostic_entry_point_group(
                        contract.goal_id,
                        contract.api_major,
                    ),
                    diagnostic_trigger_entry_point_group(
                        contract.goal_id,
                        contract.api_major,
                    ),
                ),
                (plugin_dependency_entry_point_prefix(),),
            )
        discovery = discover_plugins(
            self._application_id,
            contract,
            policy,
            directory_plugins=directory_plugins,
            plugin_directory=self._plugin_directory,
            plugin_declaration_application_ids=(
                self._plugin_declaration_application_ids
            ),
            discover_installed=discover_installed,
            entry_point_index=entry_point_index,
        )

        try:
            active_ids = frozenset(item.plugin_id for item in discovery.loaded_plugins)
            missing_required_ids = tuple(sorted(required_ids - active_ids))
            if missing_required_ids:
                raise PluginRequirementError(
                    "required plugins are unavailable: "
                    + ", ".join(repr(plugin_id) for plugin_id in missing_required_ids)
                )
            orders = resolve_discovered_plugin_orders(discovery)
        except BaseException as resolution_error:
            try:
                discovery.close()
            except Exception as cleanup_error:  # noqa: BLE001 - preserve both failures.
                raise BaseExceptionGroup(
                    "plugin resolution and endpoint cleanup failed",
                    (resolution_error, cleanup_error),
                ) from None
            raise
        self._missing_policy_ids = tuple(
            plugin_id
            for plugin_id in discovery.missing_policy_ids
            if plugin_id not in required_ids
        )
        self._packaging_warnings = discovery.packaging_warnings
        self._preprocess_order = orders.preprocess
        self._postprocess_order = orders.postprocess
        try:
            self._diagnostic_discovery = discover_diagnostics(
                contract.requirement,
                discover_installed=discover_installed,
                entry_point_index=entry_point_index,
            )
        except BaseException as diagnostic_discovery_error:
            try:
                discovery.close()
            except Exception as cleanup_error:  # noqa: BLE001 - preserve failures.
                raise BaseExceptionGroup(
                    "diagnostic discovery and plugin endpoint cleanup failed",
                    (diagnostic_discovery_error, cleanup_error),
                ) from None
            raise
        self._diagnostic_runner = BubblewrapDiagnosticRunner(isolation_config)
        try:
            self._initialize_loaded_plugins(logging_config)
        except BaseException as initialization_error:
            try:
                self.close()
            except Exception as cleanup_error:  # noqa: BLE001 - preserve both failures.
                raise BaseExceptionGroup(
                    "application construction and endpoint cleanup failed",
                    (initialization_error, cleanup_error),
                ) from None
            raise

    def _initialize_loaded_plugins(
        self,
        logging_config: LoggingConfig | None,
    ) -> None:
        for item in self._preprocess_order:
            if item.goal_requirement != self._contract.requirement:
                raise TypeError(
                    f"plugin {item.plugin_id!r} has incompatible goal requirement"
                )
        self._elevated = is_process_elevated()
        validate_plugin_elevation(
            self._preprocess_order,
            elevated=self._elevated,
        )
        self._active_plugins = tuple(
            item.active_plugin for item in self._preprocess_order
        )
        self._postprocess_plugins = tuple(
            item.active_plugin for item in self._postprocess_order
        )
        post_positions = {
            item.plugin_id: position
            for position, item in enumerate(self._postprocess_plugins, 1)
        }
        self._plugin_executions = tuple(
            PluginExecutionRecord(
                plugin=item,
                preprocess_position=position,
                postprocess_position=post_positions[item.plugin_id],
            )
            for position, item in enumerate(self._active_plugins, 1)
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
        self._activated_plugin_ids = plugin_ids
        with self._diagnostics.session() as diagnostics:
            for plugin_id in self._activated_plugin_ids:
                diagnostics.core.debug(
                    "plugin %s activated",
                    plugin_id,
                    extra={"engulf_phase": "plugin.activation"},
                )
        self._setup_goal()

    @property
    def application_id(self) -> str:
        return self._application_id

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def application_metadata(self) -> ApplicationMetadata:
        return self._application_metadata

    @property
    def vendor(self) -> str:
        return self._application_metadata.vendor

    @property
    def product(self) -> str:
        return self._application_metadata.product

    @property
    def short_product_name(self) -> str:
        return self._application_metadata.short_product_name

    @property
    def version(self) -> str:
        return self._application_metadata.version

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
    def required_plugin_ids(self) -> frozenset[str]:
        return self._required_plugin_ids

    @property
    def plugin_declaration_application_ids(self) -> tuple[str, ...]:
        return self._plugin_declaration_application_ids

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
    def application_plugin_entry_point_groups(self) -> tuple[str, ...]:
        return tuple(
            application_plugin_entry_point_group(application_id)
            for application_id in self._plugin_declaration_application_ids
        )

    @property
    def active_plugins(self) -> tuple[ActivePlugin, ...]:
        """Return implementation-free plugin descriptors in preprocessing order."""
        return self._active_plugins

    @property
    def plugins(self) -> tuple[ActivePlugin, ...]:
        """Alias for :attr:`active_plugins`."""
        return self._active_plugins

    @property
    def postprocess_plugins(self) -> tuple[ActivePlugin, ...]:
        return self._postprocess_plugins

    @property
    def diagnostic_extensions(self) -> tuple[DiagnosticExtension, ...]:
        """Return immutable import-free diagnostic-extension records."""
        return self._diagnostic_discovery.descriptors

    @property
    def diagnostic_isolation_config(self) -> DiagnosticIsolationConfig:
        return self._diagnostic_isolation

    @property
    def diagnostic_isolation(self) -> DiagnosticIsolationConfig:
        """Alias for :attr:`diagnostic_isolation_config`."""
        return self._diagnostic_isolation

    @property
    def diagnostic_entry_point_group(self) -> str:
        return diagnostic_entry_point_group(
            self._contract.goal_id, self._contract.api_major
        )

    @property
    def diagnostic_trigger_entry_point_group(self) -> str:
        return diagnostic_trigger_entry_point_group(
            self._contract.goal_id, self._contract.api_major
        )

    @property
    def plugin_directory(self) -> Path | None:
        return self._plugin_directory

    @property
    def missing_policy_ids(self) -> tuple[str, ...]:
        return self._missing_policy_ids

    @property
    def closed(self) -> bool:
        with self._lifecycle_lock:
            return self._closed

    def __enter__(self) -> Self:
        self._require_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()

    def close(self) -> None:
        """Release execution endpoints; repeated calls have no effect."""
        with self._lifecycle_lock:
            if self._closed:
                return
            if self._invocation_active:
                raise RuntimeError("cannot close application during an invocation")
            self._closed = True
        failures: list[Exception] = []
        diagnostics_manager = getattr(self, "_diagnostics", None)
        if diagnostics_manager is None:
            for item in self._preprocess_order:
                try:
                    item.endpoint.close()
                except Exception as error:  # noqa: BLE001 - extensible endpoint.
                    failures.append(error)
        else:
            with diagnostics_manager.session() as diagnostics:
                activated_ids = frozenset(getattr(self, "_activated_plugin_ids", ()))
                for item in self._preprocess_order:
                    try:
                        item.endpoint.close()
                    except Exception as error:  # noqa: BLE001 - extensible endpoint.
                        failures.append(error)
                    else:
                        if item.plugin_id in activated_ids:
                            diagnostics.core.debug(
                                "plugin %s deactivated",
                                item.plugin_id,
                                extra={"engulf_phase": "plugin.deactivation"},
                            )
        if failures:
            raise ExceptionGroup("plugin endpoint cleanup failed", failures)

    def invoke(
        self,
        argv: Sequence[str] | None = None,
        *,
        log_overrides: LogLevelOverrides | None = None,
    ) -> GoalResult[ResultT]:
        self._begin_invocation()
        try:
            return self._invoke_once(argv, log_overrides=log_overrides)
        finally:
            self._end_invocation()

    def _invoke_once(
        self,
        argv: Sequence[str] | None,
        *,
        log_overrides: LogLevelOverrides | None,
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
            matches = matching_diagnostics(self._diagnostic_discovery, received_args)
            if matches:
                with self._diagnostics.session(programmatic_overrides) as diagnostics:
                    return self._invoke_diagnostics(received_args, matches, diagnostics)
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
            normalized = self._goal.normalize_invocation(invocation)
            if not isinstance(normalized, Invocation):
                raise TypeError("goal.normalize_invocation must return an Invocation")
            invocation = normalized
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
            for warning in self._packaging_warnings:
                diagnostics.core.warning(
                    "%s",
                    warning,
                    extra={"engulf_phase": "discovery"},
                )
            plugin_apis = {
                item.plugin_id: RuntimeDiagnosticsAPI(
                    item.plugin_id,
                    diagnostics.plugin_logger(item.plugin_id),
                    application=self._application_metadata,
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
                self._application_metadata,
                tuple(item.plugin_id for item in self._preprocess_order),
                self._elevated,
            )
            try:
                self._goal.setup(api)
            except PluginCallbackError:
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

    def _invoke_diagnostics(
        self,
        arguments: tuple[str, ...],
        matches: tuple[_DiscoveredDiagnostic, ...],
        diagnostics: DiagnosticsSession,
    ) -> GoalResult[ResultT]:
        probe_error: Exception | None = None
        if self._diagnostic_discovery.isolation_available is None:
            try:
                available, reason = self._diagnostic_runner.probe(matches[0])
            except Exception as error:  # noqa: BLE001 - isolation boundary.
                probe_error = error
                available = False
                reason = f"isolation probe failed: {error}"
            self._diagnostic_discovery = (
                self._diagnostic_discovery.with_isolation_availability(
                    available,
                    reason,
                )
            )
            matches = matching_diagnostics(self._diagnostic_discovery, arguments)
            if not available:
                diagnostics.core.warning(
                    "isolated diagnostics are unavailable: %s",
                    self._diagnostic_discovery.unavailable_reason,
                    extra={"engulf_phase": "diagnostic.isolation"},
                )
        if not self._diagnostic_discovery.isolation_available:
            reason = self._diagnostic_discovery.unavailable_reason or "unknown reason"
            diagnostics.failure(
                f"diagnostic trigger rejected because isolation is unavailable: {reason}",
                phase="diagnostic.isolation",
                error=probe_error,
            )
            return GoalResult.framework_failed(error="diagnostic isolation unavailable")
        request = DiagnosticRequest(
            arguments=arguments,
            application=self._application_metadata,
            goal=self._contract.requirement,
        )
        first_nonzero = 0
        failures: list[str] = []
        successful_ids: list[str] = []
        for item in matches:
            diagnostic_id = item.descriptor.diagnostic_id
            try:
                contribution = self._diagnostic_runner.run(
                    item,
                    request,
                    self._active_plugins,
                    self._plugin_executions,
                    self._diagnostic_discovery.descriptors,
                    self._elevated,
                )
            except Exception as error:  # noqa: BLE001 - isolated worker boundary.
                failures.append(diagnostic_id)
                diagnostics.failure(
                    f"diagnostic {diagnostic_id} failed: {error}",
                    phase="diagnostic.execute",
                    error=error,
                )
                continue
            successful_ids.append(diagnostic_id)
            if contribution.stdout:
                sys.stdout.write(contribution.stdout)
                sys.stdout.flush()
            if contribution.stderr:
                sys.stderr.write(contribution.stderr)
                sys.stderr.flush()
            if first_nonzero == 0 and contribution.exit_code != 0:
                first_nonzero = contribution.exit_code
        if failures:
            return GoalResult.framework_failed(
                error="diagnostic extensions failed: " + ", ".join(failures)
            )
        return GoalResult.diagnostic(tuple(successful_ids), exit_code=first_nonzero)

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
                application=self._application_metadata,
                elevated=self._elevated,
            )
            for item in self._preprocess_order
        }

        def dispatch(
            phase: GoalPhase[Any, Any, InvocationAPI, Any],
            event: Any,
            plugin_ids: Sequence[str] | None = None,
        ) -> tuple[AttributedContribution[Any], ...]:
            return self._phase_dispatcher.dispatch_invocation(
                phase,
                event,
                plugin_apis,
                diagnostics,
                plugin_ids,
            )

        goal_api = RuntimeGoalAPI(
            participant_id=f"__goal__.{self._contract.goal_id}",
            context_reads=None,
            context_writes=None,
            context_table=context_table,
            state_manager=state_manager,
            diagnostic_logger=diagnostics.core,
            application=self._application_metadata,
            elevated=self._elevated,
            dispatch=dispatch,
        )
        entered: set[str] = set()
        cleanup_failures: tuple[WorkspaceCleanupFailure, ...] = ()
        result: GoalResult[Any] | None = None
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
                except PluginCallbackError as error:
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
            # Unread context is only a design signal on a run that reached
            # the end. A rejected, failed, or diagnostic invocation stops the
            # pipeline early, so context a later plugin would have consumed is
            # legitimately unread -- warning then buries the real failure the
            # operator needs to read.
            if (
                context_table.unused_ids
                and result is not None
                and result.status is GoalResultStatus.COMPLETED
            ):
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

    def _require_open(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("application is closed")

    def _begin_invocation(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("application is closed")
            if self._invocation_active:
                raise RuntimeError("application invocation is already active")
            self._invocation_active = True

    def _end_invocation(self) -> None:
        with self._lifecycle_lock:
            if not self._invocation_active:
                raise RuntimeError("application invocation is not active")
            self._invocation_active = False
