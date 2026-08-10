from __future__ import annotations

import errno
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import FrameType, TracebackType
from typing import Any, Self, TextIO, cast

from engulf_api import (
    AttributedContribution,
    Goal,
    GoalAPI,
    GoalContract,
    GoalPhase,
    GoalResult,
    GoalSetupAPI,
    Invocation,
    InvocationAPI,
    PluginOrder,
    RegistrationAPI,
)
from engulf_executable_wrapper_api import (
    AdditionPlacement,
    AfterCallEvent,
    ArgumentRegistry,
    BeforeCallEvent,
    CallContribution,
    CallMode,
    CallOutcome,
    CompletionCallable,
    CompletionCandidate,
    CompletionContext,
    CompletionProvider,
    CompletionRegistry,
    ExecutableWrapperPlugin,
    HelpAPI,
    OutcomeKind,
    PreparedCallEvent,
)

from engulf import LOG_LEVEL_NAMES, logging_option_names

_FORWARDED_SIGNALS = (
    signal.SIGHUP,
    signal.SIGINT,
    signal.SIGQUIT,
    signal.SIGTERM,
    signal.SIGUSR1,
    signal.SIGUSR2,
    signal.SIGWINCH,
)

type _SignalHandler = (
    Callable[[int, FrameType | None], Any] | int | signal.Handlers | None
)


@dataclass(frozen=True, slots=True)
class _SetupEvent:
    arguments: ArgumentRegistry
    completions: CompletionRegistry


def _register_arguments(
    plugin: ExecutableWrapperPlugin,
    event: _SetupEvent,
    api: RegistrationAPI,
) -> None:
    plugin.register_arguments(event.arguments, api)


def _register_completions(
    plugin: ExecutableWrapperPlugin,
    event: _SetupEvent,
    api: RegistrationAPI,
) -> None:
    plugin.register_completions(event.completions, api)


def _collect_help(
    plugin: ExecutableWrapperPlugin,
    event: _SetupEvent,
    api: RegistrationAPI,
) -> str:
    del event
    return plugin.help(cast(HelpAPI, api))


def _analyze_call(
    plugin: ExecutableWrapperPlugin,
    event: BeforeCallEvent,
    api: InvocationAPI,
) -> CallContribution | None:
    return plugin.analyze_call(event, api)


def _prepare_call(
    plugin: ExecutableWrapperPlugin,
    event: PreparedCallEvent,
    api: InvocationAPI,
) -> None:
    plugin.prepare_call(event, api)


def _after_call(
    plugin: ExecutableWrapperPlugin,
    event: AfterCallEvent,
    api: InvocationAPI,
) -> None:
    plugin.after_call(event, api)


_REGISTER_ARGUMENTS: GoalPhase[
    ExecutableWrapperPlugin, _SetupEvent, RegistrationAPI, None
] = GoalPhase(
    "org.engulf.executable-wrapper.setup.arguments",
    PluginOrder.PREPROCESS,
    _register_arguments,
)
_REGISTER_COMPLETIONS: GoalPhase[
    ExecutableWrapperPlugin, _SetupEvent, RegistrationAPI, None
] = GoalPhase(
    "org.engulf.executable-wrapper.setup.completions",
    PluginOrder.PREPROCESS,
    _register_completions,
)
_COLLECT_HELP: GoalPhase[ExecutableWrapperPlugin, _SetupEvent, RegistrationAPI, str] = (
    GoalPhase(
        "org.engulf.executable-wrapper.setup.help",
        PluginOrder.PREPROCESS,
        _collect_help,
        str,
    )
)
_ANALYZE_CALL: GoalPhase[
    ExecutableWrapperPlugin, BeforeCallEvent, InvocationAPI, CallContribution
] = GoalPhase(
    "org.engulf.executable-wrapper.call.analyze",
    PluginOrder.PREPROCESS,
    _analyze_call,
    CallContribution,
)
_PREPARE_CALL: GoalPhase[
    ExecutableWrapperPlugin, PreparedCallEvent, InvocationAPI, None
] = GoalPhase(
    "org.engulf.executable-wrapper.call.prepare",
    PluginOrder.PREPROCESS,
    _prepare_call,
)
_AFTER_CALL: GoalPhase[ExecutableWrapperPlugin, AfterCallEvent, InvocationAPI, None] = (
    GoalPhase(
        "org.engulf.executable-wrapper.call.finalize",
        PluginOrder.POSTPROCESS,
        _after_call,
    )
)


class _SignalForwarder:
    """Temporarily relay wrapper signals to one attached child process."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._pending: list[signal.Signals] = []
        self._installed: list[tuple[signal.Signals, _SignalHandler]] = []

    def __enter__(self) -> Self:
        if threading.current_thread() is not threading.main_thread():
            return self
        try:
            for signum in _FORWARDED_SIGNALS:
                previous = signal.getsignal(signum)
                if previous == signal.SIG_IGN:
                    continue
                signal.signal(signum, self._handle_signal)
                self._installed.append((signum, previous))
        except BaseException:
            self._restore()
            raise
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exception_type, exception, traceback
        self.detach()
        self._restore()

    def attach(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process
        pending, self._pending = self._pending, []
        for signum in pending:
            self.forward(signum)

    def detach(self) -> None:
        self._process = None
        self._pending.clear()

    def forward(self, signum: signal.Signals) -> None:
        process = self._process
        if process is None:
            self._pending.append(signum)
            return
        if process.poll() is not None:
            return
        try:
            process.send_signal(signum)
        except ProcessLookupError:
            pass

    def _handle_signal(self, signum: int, frame: FrameType | None) -> None:
        del frame
        self.forward(signal.Signals(signum))

    def _restore(self) -> None:
        installed, self._installed = self._installed, []
        for signum, previous in reversed(installed):
            signal.signal(signum, previous)


class ExecutableWrapperGoal(Goal[CallOutcome]):
    """Goal that transparently invokes one executable with plugin contributions."""

    _contract = GoalContract(
        ExecutableWrapperPlugin.goal_requirement,
        ExecutableWrapperPlugin,
    )

    def __init__(
        self,
        executable: str | os.PathLike[str],
        *,
        completion_provider: CompletionCallable | CompletionProvider | None = None,
    ) -> None:
        executable_value = os.fspath(executable)
        if isinstance(executable_value, bytes) or not executable_value:
            raise TypeError("executable must be a non-empty string or text path")
        if "\0" in executable_value:
            raise ValueError("executable cannot contain NUL characters")
        if (
            completion_provider is not None
            and not callable(completion_provider)
            and not isinstance(completion_provider, CompletionProvider)
        ):
            raise TypeError(
                "completion_provider must be callable, implement complete(), or be None"
            )
        self._executable = executable_value
        self._completion_provider = completion_provider
        self._arguments = ArgumentRegistry()
        self._completions = CompletionRegistry()
        self._help_blocks: tuple[str, ...] = ()
        self._display_name: str | None = None
        self._plugin_ids: tuple[str, ...] = ()
        self._setup_complete = False

    @property
    def contract(self) -> GoalContract:
        return self._contract

    @property
    def executable(self) -> str:
        return self._executable

    @property
    def arguments(self) -> ArgumentRegistry:
        return self._arguments

    @property
    def completions(self) -> CompletionRegistry:
        return self._completions

    @property
    def completion_provider(self) -> CompletionCallable | CompletionProvider | None:
        return self._completion_provider

    def setup(self, api: GoalSetupAPI) -> None:
        if self._setup_complete:
            raise RuntimeError("an ExecutableWrapperGoal can belong to one application")
        self._display_name = api.display_name
        self._plugin_ids = api.plugin_ids
        self._register_logging_arguments(api.display_name, api.plugin_ids)
        event = _SetupEvent(self._arguments, self._completions)
        api.dispatch(_REGISTER_ARGUMENTS, event)
        api.dispatch(_REGISTER_COMPLETIONS, event)
        help_blocks: list[str] = []
        for contribution in api.dispatch(_COLLECT_HELP, event):
            block = contribution.value
            if block.strip():
                help_blocks.append(block.rstrip("\r\n"))
        self._help_blocks = tuple(help_blocks)
        self._setup_complete = True

    def achieve(
        self,
        invocation: Invocation,
        api: GoalAPI,
    ) -> GoalResult[CallOutcome]:
        if not self._setup_complete:
            raise RuntimeError("executable-wrapper goal has not been set up")

        if invocation.environment.get("ENGULF_INTERNAL_PROTOCOL") == "1":
            from .completion import handle_internal_protocol

            exit_code = handle_internal_protocol(self, invocation.arguments)
            outcome = CallOutcome(
                OutcomeKind.COMPLETED,
                exit_code,
                process_started=False,
            )
            return GoalResult.completed(outcome, exit_code=exit_code)

        wrapper_args = invocation.arguments
        mode = CallMode.HELP if "--help" in wrapper_args else CallMode.NORMAL
        before_event = BeforeCallEvent(self._executable, wrapper_args, mode)
        contributions = api.dispatch(_ANALYZE_CALL, before_event)
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
            if mode is CallMode.NORMAL:
                api.dispatch(
                    _PREPARE_CALL,
                    PreparedCallEvent(
                        self._executable,
                        wrapper_args,
                        effective_args,
                        mode,
                    ),
                )
            outcome, duration = self._execute(effective_args, api)

        after_event = AfterCallEvent(
            self._executable,
            wrapper_args,
            effective_args,
            mode,
            outcome,
            duration,
        )
        api.dispatch(_AFTER_CALL, after_event)

        if mode is CallMode.HELP:
            self._write_help(sys.stdout)
        if outcome.kind is OutcomeKind.PREEMPTED:
            return GoalResult.rejected(
                outcome.exit_code,
                outcome,
                rejected_by=outcome.preempted_by,
            )
        if outcome.kind in {OutcomeKind.SPAWN_FAILED, OutcomeKind.SIGNALED}:
            return GoalResult.failed(
                outcome.exit_code,
                outcome,
                error=outcome.error,
            )
        return GoalResult.completed(outcome, exit_code=outcome.exit_code)

    def _register_logging_arguments(
        self,
        display_name: str,
        plugin_ids: tuple[str, ...],
    ) -> None:
        global_option, plugin_option = logging_option_names(display_name)
        self._arguments.option(
            global_option,
            takes_value=True,
            metavar="LEVEL",
            description=f"Set {display_name} and plugin logging levels",
            value_completer=_complete_level,
            repeatable=True,
        )
        self._arguments.option(
            plugin_option,
            takes_value=True,
            metavar="PLUGIN_ID=LEVEL",
            description="Set one plugin logging level",
            value_completer=lambda context: _complete_plugin_level(
                context,
                plugin_ids,
            ),
            repeatable=True,
        )

    @staticmethod
    def _merge_edits(
        original: tuple[str, ...],
        contributions: tuple[AttributedContribution[CallContribution], ...],
    ) -> tuple[str, ...]:
        removals: set[int] = set()
        additions: dict[AdditionPlacement, list[tuple[str, ...]]] = {
            placement: [] for placement in AdditionPlacement
        }
        seen_additions: set[tuple[str, ...]] = set()

        for collected in contributions:
            contribution = collected.value
            invalid = sorted(
                index for index in contribution.removals if index >= len(original)
            )
            if invalid:
                raise IndexError(
                    f"plugin {collected.plugin_id} removed out-of-range argument "
                    f"index {invalid[0]}"
                )
            removals.update(contribution.removals)
            for addition in contribution.additions:
                if addition.args in seen_additions:
                    continue
                seen_additions.add(addition.args)
                additions[addition.placement].append(addition.args)

        surviving = [
            argument for index, argument in enumerate(original) if index not in removals
        ]
        separator = surviving.index("--") if "--" in surviving else len(surviving)

        def flatten(groups: list[tuple[str, ...]]) -> list[str]:
            return [argument for group in groups for argument in group]

        return tuple(
            flatten(additions[AdditionPlacement.PREPEND])
            + surviving[:separator]
            + flatten(additions[AdditionPlacement.BEFORE_SEPARATOR])
            + surviving[separator:]
            + flatten(additions[AdditionPlacement.APPEND])
        )

    @staticmethod
    def _resolve_preemption(
        contributions: tuple[AttributedContribution[CallContribution], ...],
    ) -> tuple[int, str] | None:
        first_zero: tuple[int, str] | None = None
        for collected in contributions:
            exit_code = collected.value.preempt_exit_code
            if exit_code is None:
                continue
            if exit_code != 0:
                return exit_code, collected.plugin_id
            if first_zero is None:
                first_zero = exit_code, collected.plugin_id
        return first_zero

    def _resolve_executable(self) -> str:
        contains_separator = os.sep in self._executable or (
            os.altsep is not None and os.altsep in self._executable
        )
        if contains_separator:
            return str(Path(self._executable).expanduser().absolute())
        resolved = shutil.which(self._executable)
        if resolved is None:
            raise FileNotFoundError(
                errno.ENOENT,
                os.strerror(errno.ENOENT),
                self._executable,
            )
        return resolved

    def _execute(
        self,
        args: tuple[str, ...],
        api: GoalAPI,
    ) -> tuple[CallOutcome, float]:
        started_at = time.monotonic()
        try:
            executable = self._resolve_executable()
            self._reject_direct_recursion(executable)
            api.logger.debug(
                "executing %s with %d arguments",
                executable,
                len(args),
            )
            with _SignalForwarder() as signal_forwarder:
                # The child shares the wrapper's process group to preserve terminal
                # access and shell job-control behavior for interactive programs.
                process = subprocess.Popen([executable, *args])
                signal_forwarder.attach(process)
                try:
                    try:
                        return_code = process.wait()
                    except KeyboardInterrupt:
                        signal_forwarder.forward(signal.SIGINT)
                        process.wait()
                        return_code = (
                            process.returncode
                            if process.returncode is not None
                            else -signal.SIGINT
                        )
                finally:
                    signal_forwarder.detach()
        except FileNotFoundError as error:
            duration = time.monotonic() - started_at
            api.logger.error("command not found: %s", self._executable)
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
            api.logger.error("cannot execute %s: %s", self._executable, error)
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
            api.logger.error("cannot execute %s: %s", self._executable, error)
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
    def _reject_direct_recursion(executable: str) -> None:
        invoked_as = sys.argv[0]
        if not invoked_as or not os.path.exists(invoked_as):
            return
        try:
            if os.path.samefile(executable, invoked_as):
                raise OSError(
                    errno.ELOOP,
                    "wrapped executable resolves to the wrapper itself",
                    executable,
                )
        except FileNotFoundError:
            return

    def _write_help(self, stream: TextIO) -> None:
        assert self._display_name is not None
        global_option, plugin_option = logging_option_names(self._display_name)
        stream.write(f"\n{self._display_name} logging options:\n\n")
        stream.write(f"  {global_option} LEVEL\n")
        stream.write(f"  {plugin_option} PLUGIN_ID=LEVEL\n")
        if self._help_blocks:
            stream.write("\nEngulf plugin help:\n\n")
            stream.write("\n\n".join(self._help_blocks))
            stream.write("\n")
        stream.flush()


def _complete_level(context: CompletionContext) -> list[CompletionCandidate]:
    current = context.current
    return [
        CompletionCandidate(_match_level_case(name, current))
        for name in LOG_LEVEL_NAMES
        if name.startswith(current.upper())
    ]


def _complete_plugin_level(
    context: CompletionContext,
    plugin_ids: tuple[str, ...],
) -> list[CompletionCandidate]:
    current = context.current
    plugin_id, separator, level_prefix = current.partition("=")
    if not separator:
        return [
            CompletionCandidate(f"{candidate}=")
            for candidate in plugin_ids
            if candidate.startswith(current)
        ]
    if plugin_id not in plugin_ids:
        return []
    return [
        CompletionCandidate(f"{plugin_id}={_match_level_case(name, level_prefix)}")
        for name in LOG_LEVEL_NAMES
        if name.startswith(level_prefix.upper())
    ]


def _match_level_case(name: str, prefix: str) -> str:
    if prefix.islower():
        return name.lower()
    if prefix.istitle():
        return name.title()
    if prefix and not prefix.isupper():
        return prefix + name[len(prefix) :]
    return name
