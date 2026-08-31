from __future__ import annotations

import errno
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
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
    OptionSpec,
    OutcomeKind,
    PreparedCallEvent,
    Shell,
)

from engulf import FRAMEWORK_ERROR_EXIT, LOG_LEVEL_NAMES, logging_option_names

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
    phase_id="org.engulf.executable-wrapper.setup.arguments",
    order=PluginOrder.PREPROCESS,
    local_callback=_register_arguments,
)
_REGISTER_COMPLETIONS: GoalPhase[
    ExecutableWrapperPlugin, _SetupEvent, RegistrationAPI, None
] = GoalPhase(
    phase_id="org.engulf.executable-wrapper.setup.completions",
    order=PluginOrder.PREPROCESS,
    local_callback=_register_completions,
)
_COLLECT_HELP: GoalPhase[ExecutableWrapperPlugin, _SetupEvent, RegistrationAPI, str] = (
    GoalPhase(
        phase_id="org.engulf.executable-wrapper.setup.help",
        order=PluginOrder.PREPROCESS,
        local_callback=_collect_help,
        contribution_type=str,
    )
)
_ANALYZE_CALL: GoalPhase[
    ExecutableWrapperPlugin, BeforeCallEvent, InvocationAPI, CallContribution
] = GoalPhase(
    phase_id="org.engulf.executable-wrapper.call.analyze",
    order=PluginOrder.PREPROCESS,
    local_callback=_analyze_call,
    contribution_type=CallContribution,
)
_PREPARE_CALL: GoalPhase[
    ExecutableWrapperPlugin, PreparedCallEvent, InvocationAPI, None
] = GoalPhase(
    phase_id="org.engulf.executable-wrapper.call.prepare",
    order=PluginOrder.PREPROCESS,
    local_callback=_prepare_call,
)
_AFTER_CALL: GoalPhase[ExecutableWrapperPlugin, AfterCallEvent, InvocationAPI, None] = (
    GoalPhase(
        phase_id="org.engulf.executable-wrapper.call.finalize",
        order=PluginOrder.POSTPROCESS,
        local_callback=_after_call,
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
        source_completion: bool = False,
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
        if not isinstance(source_completion, bool):
            raise TypeError("source_completion must be a bool")
        self._executable = executable_value
        self._completion_provider = completion_provider
        self._source_completion = source_completion
        self._arguments = ArgumentRegistry()
        self._completions = CompletionRegistry()
        self._help_blocks: tuple[tuple[str, str], ...] = ()
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

    @property
    def source_completion(self) -> bool:
        return self._source_completion

    def setup(self, api: GoalSetupAPI) -> None:
        if self._setup_complete:
            raise RuntimeError("an ExecutableWrapperGoal can belong to one application")
        self._display_name = api.display_name
        self._plugin_ids = api.plugin_ids
        self._register_logging_arguments(api.display_name, api.plugin_ids)
        event = _SetupEvent(self._arguments, self._completions)
        api.dispatch(_REGISTER_ARGUMENTS, event)
        api.dispatch(_REGISTER_COMPLETIONS, event)
        self._completions.provider(self._complete_builtin)
        help_blocks: list[tuple[str, str]] = []
        for contribution in api.dispatch(_COLLECT_HELP, event):
            block = contribution.value
            if block.strip():
                help_blocks.append((contribution.plugin_id, block.rstrip("\r\n")))
        self._help_blocks = tuple(help_blocks)
        self._setup_complete = True

    def normalize_invocation(self, invocation: Invocation) -> Invocation:
        if invocation.environment.get("ENGULF_INTERNAL_PROTOCOL") == "1":
            return invocation
        arguments, environment = self._normalize_environment_options(
            invocation.arguments,
            invocation.environment,
        )
        if arguments == invocation.arguments and environment == invocation.environment:
            return invocation
        return Invocation(arguments, invocation.cwd, environment)

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
        if wrapper_args and wrapper_args[0] == "install-completion":
            return self._install_completion(invocation, api)
        mode = CallMode.HELP if "--help" in wrapper_args else CallMode.NORMAL
        before_event = BeforeCallEvent(
            self._executable,
            wrapper_args,
            mode,
            invocation.environment,
        )
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
                try:
                    api.dispatch(
                        _PREPARE_CALL,
                        PreparedCallEvent(
                            self._executable,
                            wrapper_args,
                            effective_args,
                            mode,
                            invocation.environment,
                        ),
                    )
                except BaseException as error:
                    outcome = CallOutcome(
                        OutcomeKind.FRAMEWORK_FAILED,
                        FRAMEWORK_ERROR_EXIT,
                        process_started=False,
                        error=str(error),
                    )
                    api.dispatch(
                        _AFTER_CALL,
                        AfterCallEvent(
                            self._executable,
                            wrapper_args,
                            effective_args,
                            mode,
                            outcome,
                            0.0,
                            invocation.environment,
                        ),
                    )
                    raise
            outcome, duration = self._execute(effective_args, api)

        after_event = AfterCallEvent(
            self._executable,
            wrapper_args,
            effective_args,
            mode,
            outcome,
            duration,
            invocation.environment,
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

    def _normalize_environment_options(
        self,
        arguments: tuple[str, ...],
        environment: Mapping[str, str],
    ) -> tuple[tuple[str, ...], dict[str, str]]:
        normalized: list[str] = []
        effective_environment = dict(environment)
        used: set[str] = set()
        index = 0
        while index < len(arguments):
            argument = arguments[index]
            if argument == "--":
                normalized.extend(arguments[index:])
                break
            assignment = self._arguments.find_assignment(argument)
            if assignment is not None:
                spec, _name, value = assignment
                if spec.environment is None:
                    normalized.append(argument)
                else:
                    self._set_environment_option(
                        spec, value, effective_environment, used
                    )
                index += 1
                continue
            exact_spec = self._arguments.find_exact(argument)
            if exact_spec is None or exact_spec.environment is None:
                normalized.append(argument)
                index += 1
                continue
            if exact_spec.takes_value:
                if index + 1 >= len(arguments) or arguments[index + 1] == "--":
                    raise ValueError(f"{argument} requires a value")
                value = arguments[index + 1]
                index += 2
            else:
                value = "1"
                index += 1
            self._set_environment_option(
                exact_spec,
                value,
                effective_environment,
                used,
            )
        return tuple(normalized), effective_environment

    @staticmethod
    def _set_environment_option(
        spec: OptionSpec,
        value: str,
        environment: dict[str, str],
        used: set[str],
    ) -> None:
        assert spec.environment is not None
        if spec.environment in used and not spec.repeatable:
            raise ValueError(f"option {spec.names[0]} may be supplied only once")
        used.add(spec.environment)
        environment[spec.environment] = value

    def _complete_builtin(
        self, context: CompletionContext
    ) -> list[CompletionCandidate]:
        if context.cursor_index == 0:
            return [
                CompletionCandidate(
                    "install-completion",
                    "Install completion for this wrapper command",
                )
            ]
        if not context.words or context.words[0] != "install-completion":
            return []
        if context.current.startswith("--output="):
            name, _, value = context.current.partition("=")
            return [
                CompletionCandidate(f"{name}={candidate.value}")
                for candidate in self._path_candidates(value)
            ]
        if context.previous == "--output":
            return self._path_candidates(context.current)
        if context.current.startswith("-"):
            return [CompletionCandidate("--output=", "Write to an explicit path")]
        if context.cursor_index == 1:
            return [
                CompletionCandidate(shell.value, f"Install {shell.value} completion")
                for shell in Shell
            ]
        return []

    @staticmethod
    def _path_candidates(current: str) -> list[CompletionCandidate]:
        separator = current.rfind("/")
        shown_parent = current[: separator + 1] if separator >= 0 else ""
        prefix = current[separator + 1 :]
        try:
            directory = Path(shown_parent or ".").expanduser()
        except RuntimeError:
            return []
        try:
            entries = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError:
            return []
        result: list[CompletionCandidate] = []
        for entry in entries:
            if not entry.name.startswith(prefix):
                continue
            value = f"{shown_parent}{entry.name}"
            if entry.is_dir():
                value += "/"
            result.append(CompletionCandidate(value))
        return result

    def _install_completion(
        self,
        invocation: Invocation,
        api: GoalAPI,
    ) -> GoalResult[CallOutcome]:
        if any(argument in {"-h", "--help"} for argument in invocation.arguments[1:]):
            print("usage: install-completion [bash|zsh|fish] [--output PATH]")
            outcome = CallOutcome(OutcomeKind.COMPLETED, 0, process_started=False)
            return GoalResult.completed(outcome)
        try:
            shell, output = self._completion_install_arguments(
                invocation.arguments[1:],
                invocation.environment,
                invocation.cwd,
            )
            assert self._display_name is not None
            from .completion import render_completion_script

            target = output or self._completion_install_path(
                shell,
                self._display_name,
                invocation.environment,
            )
            self._validate_completion_target(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            script = render_completion_script(
                shell,
                self._display_name,
                Path(self._executable).name,
                completion_source=(
                    self._executable if self._source_completion else None
                ),
            )
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.",
                dir=target.parent,
                text=True,
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(script)
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.chmod(0o644)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            api.logger.error("cannot install completion: %s", error)
            outcome = CallOutcome(OutcomeKind.COMPLETED, 2, process_started=False)
            return GoalResult.completed(outcome, exit_code=2)

        print(
            f"Installed {shell.value} completion for {self._display_name} at {target}"
        )
        if shell is Shell.ZSH:
            print(f"Ensure {target.parent} is on fpath before running compinit.")
        outcome = CallOutcome(OutcomeKind.COMPLETED, 0, process_started=False)
        return GoalResult.completed(outcome)

    @staticmethod
    def _completion_install_arguments(
        arguments: tuple[str, ...],
        environment: Mapping[str, str],
        cwd: Path,
    ) -> tuple[Shell, Path | None]:
        shell: Shell | None = None
        output: Path | None = None
        index = 0
        while index < len(arguments):
            argument = arguments[index]
            if argument == "--output":
                if index + 1 >= len(arguments):
                    raise ValueError("--output requires a path")
                raw_output = arguments[index + 1]
                index += 2
            elif argument.startswith("--output="):
                raw_output = argument.partition("=")[2]
                index += 1
            elif argument.startswith("-"):
                raise ValueError(f"unknown install-completion option: {argument}")
            elif shell is None:
                try:
                    shell = Shell(argument)
                except ValueError as error:
                    raise ValueError(
                        f"unsupported completion shell: {argument}"
                    ) from error
                index += 1
                continue
            else:
                raise ValueError(f"unexpected install-completion argument: {argument}")
            if not raw_output:
                raise ValueError("--output path must not be empty")
            candidate = Path(raw_output).expanduser()
            output = candidate if candidate.is_absolute() else cwd / candidate
        if shell is None:
            selected = Path(environment.get("SHELL", "")).name
            try:
                shell = Shell(selected)
            except ValueError as error:
                raise ValueError(
                    "cannot detect a supported shell; specify bash, zsh, or fish"
                ) from error
        return shell, output

    @staticmethod
    def _validate_completion_target(target: Path) -> None:
        if target.is_symlink():
            raise ValueError(f"refusing to replace symlink: {target}")
        if not target.exists():
            return
        if not target.is_file():
            raise ValueError(f"completion target is not a regular file: {target}")
        with target.open("r", encoding="utf-8") as stream:
            marker = stream.read(128)
        generated_marker = "# Generated by engulf-completion"
        if (
            not marker.startswith(generated_marker)
            and f"\n{generated_marker}" not in marker
        ):
            raise ValueError(
                f"refusing to replace unrecognized completion file: {target}"
            )

    @staticmethod
    def _completion_install_path(
        shell: Shell,
        command: str,
        environment: Mapping[str, str],
    ) -> Path:
        if not command or Path(command).name != command:
            raise ValueError("wrapper display name must be one command token")
        home = Path(environment.get("HOME", "")).expanduser()
        if not home.is_absolute():
            raise ValueError("HOME must be an absolute path")
        data_home = Path(environment.get("XDG_DATA_HOME", home / ".local" / "share"))
        config_home = Path(environment.get("XDG_CONFIG_HOME", home / ".config"))
        if not data_home.is_absolute():
            raise ValueError("XDG_DATA_HOME must be an absolute path")
        if not config_home.is_absolute():
            raise ValueError("XDG_CONFIG_HOME must be an absolute path")
        if shell is Shell.BASH:
            return data_home / "bash-completion" / "completions" / command
        if shell is Shell.ZSH:
            return data_home / "zsh" / "site-functions" / f"_{command}"
        return config_home / "fish" / "completions" / f"{command}.fish"

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
        stream.write("\nEngulf wrapper commands:\n\n")
        stream.write(
            "  install-completion [bash|zsh|fish] [--output PATH]  "
            "Install shell completion\n"
        )
        if self._help_blocks:
            stream.write("\nEngulf plugin help:\n")
            for plugin_id, block in self._help_blocks:
                heading = f"Plugin: {plugin_id}"
                stream.write(f"\n{heading}\n")
                stream.write(f"{'-' * len(heading)}\n")
                stream.write(f"{block}\n")
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
