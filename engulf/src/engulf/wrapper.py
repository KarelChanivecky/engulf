from __future__ import annotations

import errno
import os
import shutil
import signal
import subprocess
import sys
import time
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from engulf_api import (
    AdditionPlacement,
    AfterCallEvent,
    ArgumentRegistry,
    BeforeCallEvent,
    CallMode,
    CallOutcome,
    CompletionCallable,
    CompletionProvider,
    CompletionRegistry,
    OutcomeKind,
    Plugin,
    UnusedContextWarning,
    plugin_name,
)

from .plugin_api import CallContextTable, PluginContribution, RuntimePluginAPI
from .plugin_loader import (
    load_directory_plugins,
    load_installed_plugins,
    normalize_application_id,
    plugin_entry_point_group,
    resolve_plugin_directory,
    resolve_plugin_orders,
)
from .state import (
    CallStateManager,
    StateHomeResolver,
    WorkspaceCleanupFailure,
    WorkspaceRootResolver,
)

FRAMEWORK_ERROR_EXIT = 70


@dataclass(frozen=True, slots=True)
class _CollectedContribution:
    plugin: Plugin
    value: PluginContribution


class Engulf:
    def __init__(
        self,
        binary: str | os.PathLike[str],
        application_id: str,
        *,
        plugin_dir: str | os.PathLike[str] | None = None,
        discover_installed: bool = True,
        completion_provider: CompletionCallable | CompletionProvider | None = None,
        workspace_root_resolver: WorkspaceRootResolver | None = None,
        state_home_resolver: StateHomeResolver | None = None,
    ) -> None:
        binary_value = os.fspath(binary)
        if isinstance(binary_value, bytes) or not binary_value:
            raise TypeError("binary must be a non-empty string or text path")
        if "\0" in binary_value:
            raise ValueError("binary cannot contain NUL characters")
        if not isinstance(discover_installed, bool):
            raise TypeError("discover_installed must be a boolean")
        if workspace_root_resolver is not None and not callable(
            workspace_root_resolver
        ):
            raise TypeError("workspace_root_resolver must be callable")
        if state_home_resolver is not None and not callable(state_home_resolver):
            raise TypeError("state_home_resolver must be callable")

        self._binary = binary_value
        self._application_id = normalize_application_id(application_id)
        self._plugin_entry_point_group = plugin_entry_point_group(application_id)
        self._plugin_directory = (
            None if plugin_dir is None else resolve_plugin_directory(plugin_dir)
        )
        directory_plugins = (
            ()
            if self._plugin_directory is None
            else load_directory_plugins(self._plugin_directory)
        )
        installed_plugins = (
            load_installed_plugins(self._application_id) if discover_installed else ()
        )
        orders = resolve_plugin_orders(directory_plugins + installed_plugins)
        self._preprocess_order = orders.preprocess
        self._postprocess_order = orders.postprocess
        self._plugins = tuple(item.plugin for item in self._preprocess_order)
        self._postprocess_plugins = tuple(
            item.plugin for item in self._postprocess_order
        )
        self._completion_provider = completion_provider
        self._workspace_root_resolver = workspace_root_resolver
        self._state_home_resolver = state_home_resolver
        self._arguments = ArgumentRegistry()
        self._completions = CompletionRegistry()

        for plugin in self._plugins:
            plugin.register_arguments(self._arguments)
            plugin.register_completions(self._completions)

    @property
    def binary(self) -> str:
        return self._binary

    @property
    def application_id(self) -> str:
        return self._application_id

    @property
    def plugin_entry_point_group(self) -> str:
        return self._plugin_entry_point_group

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
    def arguments(self) -> ArgumentRegistry:
        return self._arguments

    @property
    def completions(self) -> CompletionRegistry:
        return self._completions

    @property
    def completion_provider(self) -> CompletionCallable | CompletionProvider | None:
        return self._completion_provider

    def run(self, argv: Sequence[str] | None = None) -> int:
        if os.environ.get("ENGULF_INTERNAL_PROTOCOL") == "1":
            from .completion import handle_internal_protocol

            return handle_internal_protocol(
                self, tuple(sys.argv[1:] if argv is None else argv)
            )

        try:
            wrapper_args = tuple(sys.argv[1:] if argv is None else argv)
            self._validate_args(wrapper_args)
        except (TypeError, ValueError) as error:
            self._report_error(f"invalid wrapper arguments: {error}")
            return FRAMEWORK_ERROR_EXIT

        mode = CallMode.HELP if "--help" in wrapper_args else CallMode.NORMAL
        try:
            cwd = Path.cwd().resolve(strict=True)
        except OSError as error:
            self._report_error(f"cannot resolve current directory: {error}")
            return FRAMEWORK_ERROR_EXIT

        state_manager = CallStateManager(
            application_id=self._application_id,
            binary=self._binary,
            wrapper_args=wrapper_args,
            mode=mode,
            cwd=cwd,
            workspace_root_resolver=self._workspace_root_resolver,
            state_home_resolver=self._state_home_resolver,
            environment=dict(os.environ),
            effective_uid=os.geteuid(),
            effective_gid=os.getegid(),
        )
        context_table = CallContextTable()
        apis = self._create_plugin_apis(len(wrapper_args), context_table, state_manager)
        cleanup_failures: tuple[WorkspaceCleanupFailure, ...] = ()
        try:
            result = self._run_call(wrapper_args, mode, apis)
        finally:
            cleanup_failures = state_manager.finalize_destructions()
            for failure in cleanup_failures:
                self._report_error(
                    "workspace state cleanup failed for "
                    f"{failure.plugin_id} at {failure.root}: {failure.error}"
                )
            for api in apis.values():
                api.close()
            unused_ids = context_table.unused_ids
            if unused_ids:
                warnings.warn(
                    "context written but never read: " + ", ".join(unused_ids),
                    UnusedContextWarning,
                    stacklevel=2,
                )
        if cleanup_failures:
            return FRAMEWORK_ERROR_EXIT
        return result

    def _run_call(
        self,
        wrapper_args: tuple[str, ...],
        mode: CallMode,
        apis: dict[str, RuntimePluginAPI],
    ) -> int:
        before_event = BeforeCallEvent(self._binary, wrapper_args, mode)
        contributions: list[_CollectedContribution] = []

        for item in self._preprocess_order:
            plugin = item.plugin
            api = apis[item.plugin_id]
            error: Exception | None = None
            api.activate_preprocess()
            try:
                plugin.before_call(before_event, api)
            except Exception as caught:  # noqa: BLE001 - plugins are a trust boundary.
                error = caught
            finally:
                api.deactivate()

            if error is not None:
                self._report_plugin_error(plugin, "before_call", error)
                outcome = CallOutcome(
                    OutcomeKind.FRAMEWORK_FAILED,
                    FRAMEWORK_ERROR_EXIT,
                    process_started=False,
                    error=str(error),
                )
                after_event = AfterCallEvent(
                    self._binary,
                    wrapper_args,
                    wrapper_args,
                    mode,
                    outcome,
                    0.0,
                )
                self._dispatch_after(after_event, apis)
                return FRAMEWORK_ERROR_EXIT
            contributions.append(_CollectedContribution(plugin, api.freeze()))

        effective_args = (
            wrapper_args
            if mode is CallMode.HELP
            else self._merge_edits(wrapper_args, contributions)
        )
        preemption = (
            None if mode is CallMode.HELP else self._resolve_preemption(contributions)
        )

        if preemption is not None:
            exit_code, source = preemption
            outcome = CallOutcome(
                OutcomeKind.PREEMPTED,
                exit_code,
                process_started=False,
                preempted_by=source,
            )
            duration = 0.0
        else:
            outcome, duration = self._execute(effective_args)

        after_event = AfterCallEvent(
            self._binary,
            wrapper_args,
            effective_args,
            mode,
            outcome,
            duration,
        )
        if not self._dispatch_after(after_event, apis):
            return FRAMEWORK_ERROR_EXIT

        if mode is CallMode.HELP and not self._write_plugin_help(sys.stdout):
            return FRAMEWORK_ERROR_EXIT
        return outcome.exit_code

    def _create_plugin_apis(
        self,
        argument_count: int,
        context_table: CallContextTable,
        state_manager: CallStateManager,
    ) -> dict[str, RuntimePluginAPI]:
        return {
            item.plugin_id: RuntimePluginAPI(
                plugin_id=item.plugin_id,
                argument_count=argument_count,
                context_reads=item.context_reads,
                context_writes=item.context_writes,
                context_table=context_table,
                state_manager=state_manager,
            )
            for item in self._preprocess_order
        }

    @staticmethod
    def _validate_args(args: tuple[str, ...]) -> None:
        if any(not isinstance(arg, str) for arg in args):
            raise TypeError("all arguments must be strings")
        if any("\0" in arg for arg in args):
            raise ValueError("arguments cannot contain NUL characters")

    @staticmethod
    def _merge_edits(
        original: tuple[str, ...],
        contributions: list[_CollectedContribution],
    ) -> tuple[str, ...]:
        removals: set[int] = set()
        additions: dict[AdditionPlacement, list[tuple[str, ...]]] = {
            placement: [] for placement in AdditionPlacement
        }
        seen_additions: set[tuple[str, ...]] = set()

        for collected in contributions:
            removals.update(collected.value.removals)
            for addition in collected.value.additions:
                if addition.args in seen_additions:
                    continue
                seen_additions.add(addition.args)
                additions[addition.placement].append(addition.args)

        surviving = [arg for index, arg in enumerate(original) if index not in removals]
        separator = surviving.index("--") if "--" in surviving else len(surviving)

        def flatten(groups: list[tuple[str, ...]]) -> list[str]:
            return [arg for group in groups for arg in group]

        return tuple(
            flatten(additions[AdditionPlacement.PREPEND])
            + surviving[:separator]
            + flatten(additions[AdditionPlacement.BEFORE_SEPARATOR])
            + surviving[separator:]
            + flatten(additions[AdditionPlacement.APPEND])
        )

    @staticmethod
    def _resolve_preemption(
        contributions: list[_CollectedContribution],
    ) -> tuple[int, str] | None:
        first_zero: tuple[int, str] | None = None
        for collected in contributions:
            exit_code = collected.value.preemption
            if exit_code is None:
                continue
            source = plugin_name(collected.plugin)
            if exit_code != 0:
                return exit_code, source
            if first_zero is None:
                first_zero = exit_code, source
        return first_zero

    def _resolve_binary(self) -> str:
        contains_separator = os.sep in self._binary or (
            os.altsep is not None and os.altsep in self._binary
        )
        if contains_separator:
            return str(Path(self._binary).expanduser().absolute())
        resolved = shutil.which(self._binary)
        if resolved is None:
            raise FileNotFoundError(
                errno.ENOENT, os.strerror(errno.ENOENT), self._binary
            )
        return resolved

    def _execute(self, args: tuple[str, ...]) -> tuple[CallOutcome, float]:
        started_at = time.monotonic()
        try:
            binary = self._resolve_binary()
            self._reject_direct_recursion(binary)
            process = subprocess.Popen([binary, *args])
            try:
                return_code = process.wait()
            except KeyboardInterrupt:
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
                process.wait()
                return_code = (
                    process.returncode
                    if process.returncode is not None
                    else -signal.SIGINT
                )
        except FileNotFoundError as error:
            duration = time.monotonic() - started_at
            self._report_error(f"command not found: {self._binary}")
            return (
                CallOutcome(
                    OutcomeKind.SPAWN_FAILED,
                    127,
                    process_started=False,
                    error=str(error),
                ),
                duration,
            )
        except PermissionError as error:
            duration = time.monotonic() - started_at
            self._report_error(f"cannot execute {self._binary}: {error.strerror}")
            return (
                CallOutcome(
                    OutcomeKind.SPAWN_FAILED,
                    126,
                    process_started=False,
                    error=str(error),
                ),
                duration,
            )
        except OSError as error:
            duration = time.monotonic() - started_at
            self._report_error(f"cannot execute {self._binary}: {error}")
            return (
                CallOutcome(
                    OutcomeKind.SPAWN_FAILED,
                    126,
                    process_started=False,
                    error=str(error),
                ),
                duration,
            )

        duration = time.monotonic() - started_at
        if return_code < 0:
            terminating_signal = -return_code
            return (
                CallOutcome(
                    OutcomeKind.SIGNALED,
                    min(255, 128 + terminating_signal),
                    process_started=True,
                    signal=terminating_signal,
                ),
                duration,
            )
        return (
            CallOutcome(
                OutcomeKind.COMPLETED,
                return_code,
                process_started=True,
            ),
            duration,
        )

    @staticmethod
    def _reject_direct_recursion(binary: str) -> None:
        invoked_as = sys.argv[0]
        if not invoked_as or not os.path.exists(invoked_as):
            return
        try:
            if os.path.samefile(binary, invoked_as):
                raise OSError(
                    errno.ELOOP, "wrapped binary resolves to the wrapper itself", binary
                )
        except FileNotFoundError:
            return

    def _dispatch_after(
        self,
        event: AfterCallEvent,
        apis: dict[str, RuntimePluginAPI],
    ) -> bool:
        for item in self._postprocess_order:
            plugin = item.plugin
            api = apis[item.plugin_id]
            error: Exception | None = None
            api.activate_postprocess()
            try:
                plugin.after_call(event, api)
            except Exception as caught:  # noqa: BLE001 - plugins are a trust boundary.
                error = caught
            finally:
                api.deactivate()

            if error is not None:
                self._report_plugin_error(plugin, "after_call", error)
                return False
        return True

    def _write_plugin_help(self, stream: TextIO) -> bool:
        help_blocks: list[str] = []
        for plugin in self._plugins:
            try:
                block = plugin.help()
            except Exception as error:  # noqa: BLE001 - plugins are a trust boundary.
                self._report_plugin_error(plugin, "help", error)
                return False
            if not isinstance(block, str):
                self._report_error(
                    f"{plugin_name(plugin)}.help() did not return a string"
                )
                return False
            if block.strip():
                help_blocks.append(block.rstrip("\r\n"))

        if help_blocks:
            stream.write("\nEngulf plugin help:\n\n")
            stream.write("\n\n".join(help_blocks))
            stream.write("\n")
            stream.flush()
        return True

    @staticmethod
    def _report_error(message: str) -> None:
        print(f"engulf: {message}", file=sys.stderr)

    def _report_plugin_error(self, plugin: Plugin, hook: str, error: Exception) -> None:
        self._report_error(f"plugin {plugin_name(plugin)} failed in {hook}: {error}")
