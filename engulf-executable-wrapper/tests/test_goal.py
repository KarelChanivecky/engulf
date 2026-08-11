from __future__ import annotations

import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from itertools import count
from pathlib import Path
from unittest.mock import patch

from engulf_executable_wrapper import ExecutableWrapperGoal
from engulf_executable_wrapper_api import (
    AdditionPlacement,
    ArgumentAddition,
    CallContribution,
    CallMode,
    ExecutableWrapperPlugin,
    OutcomeKind,
)

from engulf import FRAMEWORK_ERROR_EXIT, Application

FAKE_BINARY = """#!{python}
import json
import os
import signal
import sys
from pathlib import Path

record = os.environ.get("ENGULF_TEST_RECORD")
if record:
    Path(record).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
message = os.environ.get("ENGULF_TEST_STDOUT")
if message:
    print(message)
signal_number = os.environ.get("ENGULF_TEST_SIGNAL")
if signal_number:
    os.kill(os.getpid(), int(signal_number))
raise SystemExit(int(os.environ.get("ENGULF_TEST_EXIT", "0")))
"""

WAITING_BINARY = """#!{python}
import os
import signal
from pathlib import Path

signal.signal(signal.SIGINT, signal.SIG_DFL)
Path(os.environ["ENGULF_SIGNAL_READY"]).write_text(
    f"{{os.getpid()}} {{os.getpgrp()}}",
    encoding="utf-8",
)
while True:
    signal.pause()
"""

SIGNAL_PLUGIN = """from __future__ import annotations

import json
import os
from pathlib import Path

from engulf_executable_wrapper_api import ExecutableWrapperPlugin


class SignalPlugin(ExecutableWrapperPlugin):
    plugin_id = "tests.wrapper.signal"

    def help(self, api) -> str:
        del api
        return ""

    def after_call(self, event, api) -> None:
        Path(os.environ["ENGULF_SIGNAL_OUTCOME"]).write_text(
            json.dumps(
                {
                    "kind": event.outcome.kind.value,
                    "exit_code": event.outcome.exit_code,
                    "signal": event.outcome.signal,
                }
            ),
            encoding="utf-8",
        )


plugin = SignalPlugin()
"""

SIGNAL_WRAPPER = """import os

from engulf import Application
from engulf_executable_wrapper import ExecutableWrapperGoal


application = Application(
    "engulf-signal-forwarding-tests",
    ExecutableWrapperGoal(os.environ["ENGULF_SIGNAL_BINARY"]),
    display_name="engulf-signal-tests",
    plugin_dir=os.environ["ENGULF_SIGNAL_PLUGIN_DIR"],
    discover_installed=False,
)
raise SystemExit(application.run([]))
"""

_plugin_ids = count()


class _ContributionBuilder:
    def __init__(self) -> None:
        self.removals: set[int] = set()
        self.additions: list[ArgumentAddition] = []
        self.preemption: int | None = None

    def remove(self, index: int) -> None:
        self.removals.add(index)

    def remove_range(self, start: int, stop: int) -> None:
        self.removals.update(range(start, stop))

    def add(
        self,
        *args: str,
        placement: AdditionPlacement = AdditionPlacement.BEFORE_SEPARATOR,
    ) -> None:
        self.additions.append(ArgumentAddition(tuple(args), placement))

    def preempt(self, exit_code: int) -> None:
        self.preemption = exit_code

    def freeze(self) -> CallContribution:
        return CallContribution(
            frozenset(self.removals),
            tuple(self.additions),
            self.preemption,
        )


class RecordingPlugin(ExecutableWrapperPlugin):
    def __init__(
        self,
        *,
        plugin_id: str | None = None,
        priority: int = 50,
        help_text: str = "",
        before=None,
        prepare=None,
        after=None,
    ) -> None:
        self.plugin_id = plugin_id or f"tests.wrapper.plugin{next(_plugin_ids)}"
        self.priority = priority
        self.help_text = help_text
        self.before_action = before
        self.prepare_action = prepare
        self.after_action = after
        self.before_events = []
        self.prepare_events = []
        self.after_events = []

    def help(self, api) -> str:
        del api
        return self.help_text

    def analyze_call(self, event, api) -> CallContribution | None:
        self.before_events.append(event)
        builder = _ContributionBuilder()
        if self.before_action is not None:
            self.before_action(event, builder)
            return builder.freeze()
        return None

    def prepare_call(self, event, api) -> None:
        self.prepare_events.append(event)
        if self.prepare_action is not None:
            self.prepare_action(event, api)

    def after_call(self, event, api) -> None:
        self.after_events.append(event)
        if self.after_action is not None:
            self.after_action(event, api)


class ExecutableWrapperGoalTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)
        self.plugin_directory = self.directory / "plugins"
        self.plugin_directory.mkdir()
        self.binary = self.directory / "fake-command"
        self.binary.write_text(
            FAKE_BINARY.format(python=sys.executable),
            encoding="utf-8",
        )
        self.binary.chmod(0o755)
        self.record = self.directory / "argv.json"

    def make_application(
        self,
        *plugins: ExecutableWrapperPlugin,
        binary: str | os.PathLike[str] | None = None,
    ) -> Application:
        with patch(
            "engulf.application.load_directory_plugins", return_value=tuple(plugins)
        ):
            return Application(
                "engulf-lifecycle-tests",
                ExecutableWrapperGoal(binary or self.binary),
                display_name="engulf-lifecycle-tests",
                plugin_dir=self.plugin_directory,
                discover_installed=False,
            )

    def run_application(
        self,
        application: Application,
        args: list[str],
        **environment: str,
    ) -> int:
        values = {"ENGULF_TEST_RECORD": str(self.record), **environment}
        with patch.dict(os.environ, values, clear=False):
            return application.run(args)

    def recorded_args(self) -> list[str]:
        return json.loads(self.record.read_text(encoding="utf-8"))

    def test_passes_arguments_and_emits_events(self) -> None:
        plugin = RecordingPlugin()
        engulf = self.make_application(plugin)

        result = self.run_application(engulf, ["one", "two words", "--flag=value"])

        self.assertEqual(result, 0)
        self.assertEqual(self.recorded_args(), ["one", "two words", "--flag=value"])
        self.assertEqual(
            plugin.before_events[0].wrapper_args, ("one", "two words", "--flag=value")
        )
        self.assertEqual(
            plugin.after_events[0].effective_args, ("one", "two words", "--flag=value")
        )
        self.assertEqual(plugin.after_events[0].outcome.kind, OutcomeKind.COMPLETED)

    def test_merges_deferred_removals_and_isolated_additions(self) -> None:
        seen = []

        def first(event, edits) -> None:
            seen.append(event.wrapper_args)
            edits.remove(1)
            edits.add("--global", placement=AdditionPlacement.PREPEND)
            edits.add("--one", "two")
            edits.add("--after", placement=AdditionPlacement.APPEND)

        def second(event, edits) -> None:
            seen.append(event.wrapper_args)
            edits.remove(1)
            edits.add("--one", "two", placement=AdditionPlacement.APPEND)
            edits.add("--one", "three")

        plugins = [RecordingPlugin(before=first), RecordingPlugin(before=second)]
        engulf = self.make_application(*plugins)
        original = ["keep", "drop", "--", "tail"]

        result = self.run_application(engulf, original)

        self.assertEqual(result, 0)
        self.assertEqual(seen, [tuple(original), tuple(original)])
        self.assertEqual(
            self.recorded_args(),
            [
                "--global",
                "keep",
                "--one",
                "two",
                "--one",
                "three",
                "--",
                "tail",
                "--after",
            ],
        )
        for plugin in plugins:
            self.assertEqual(plugin.after_events[0].wrapper_args, tuple(original))
            self.assertEqual(
                plugin.after_events[0].effective_args, tuple(self.recorded_args())
            )

    def test_additions_are_not_coalesced_against_original_arguments(self) -> None:
        plugin = RecordingPlugin(
            before=lambda event, edits: edits.add("--same", "value")
        )
        engulf = self.make_application(plugin)

        result = self.run_application(engulf, ["--same", "value"])

        self.assertEqual(result, 0)
        self.assertEqual(
            self.recorded_args(),
            ["--same", "value", "--same", "value"],
        )

    def test_first_nonzero_preemption_wins_and_all_plugins_run(self) -> None:
        calls = []

        def preempt(name: str, code: int):
            def action(event, edits) -> None:
                calls.append(name)
                edits.preempt(code)

            return action

        plugins = [
            RecordingPlugin(before=preempt("zero", 0)),
            RecordingPlugin(before=preempt("seven", 7)),
            RecordingPlugin(before=preempt("nine", 9)),
        ]
        engulf = self.make_application(*plugins)

        result = self.run_application(engulf, ["not-executed"])

        self.assertEqual(result, 7)
        self.assertEqual(calls, ["zero", "seven", "nine"])
        self.assertFalse(self.record.exists())
        for plugin in plugins:
            self.assertEqual(plugin.after_events[0].outcome.kind, OutcomeKind.PREEMPTED)
            self.assertEqual(plugin.after_events[0].outcome.exit_code, 7)
            self.assertEqual(
                plugin.after_events[0].outcome.preempted_by,
                plugins[1].plugin_id,
            )

    def test_priority_orders_activation_and_preserves_ties(self) -> None:
        calls = []

        class OrderedPlugin(RecordingPlugin):
            def __init__(self, name: str, priority: int) -> None:
                super().__init__(priority=priority)
                self.name = name

            def register_arguments(self, registry, api) -> None:
                del api
                calls.append((self.name, "arguments"))

            def register_completions(self, registry, api) -> None:
                del api
                calls.append((self.name, "completions"))

            def analyze_call(self, event, api) -> CallContribution | None:
                calls.append((self.name, "before"))
                return super().analyze_call(event, api)

            def after_call(self, event, api) -> None:
                calls.append((self.name, "after"))
                super().after_call(event, api)

        plugins = [
            OrderedPlugin("low", -5),
            OrderedPlugin("equal-first", 10),
            OrderedPlugin("high", 100),
            OrderedPlugin("equal-second", 10),
        ]

        engulf = self.make_application(*plugins)
        result = self.run_application(engulf, [])

        self.assertEqual(result, 0)
        names_by_id = {plugin.plugin_id: plugin.name for plugin in plugins}
        self.assertEqual(
            [names_by_id[plugin.plugin_id] for plugin in engulf.plugins],
            ["high", "equal-first", "equal-second", "low"],
        )
        self.assertEqual(
            calls,
            [
                ("high", "arguments"),
                ("equal-first", "arguments"),
                ("equal-second", "arguments"),
                ("low", "arguments"),
                ("high", "completions"),
                ("equal-first", "completions"),
                ("equal-second", "completions"),
                ("low", "completions"),
                ("high", "before"),
                ("equal-first", "before"),
                ("equal-second", "before"),
                ("low", "before"),
                ("high", "after"),
                ("equal-first", "after"),
                ("equal-second", "after"),
                ("low", "after"),
            ],
        )

    def test_highest_priority_nonzero_preemption_wins(self) -> None:
        calls = []

        def preempt(name: str, code: int):
            def action(event, edits) -> None:
                calls.append(name)
                edits.preempt(code)

            return action

        low = RecordingPlugin(priority=0, before=preempt("low", 7))
        high = RecordingPlugin(priority=100, before=preempt("high", 9))

        result = self.run_application(self.make_application(low, high), [])

        self.assertEqual(result, 9)
        self.assertEqual(calls, ["high", "low"])

    def test_zero_preemption_skips_binary(self) -> None:
        plugin = RecordingPlugin(before=lambda event, edits: edits.preempt(0))

        result = self.run_application(self.make_application(plugin), [])

        self.assertEqual(result, 0)
        self.assertFalse(self.record.exists())

    def test_preemption_resolves_before_any_prepare_side_effects(self) -> None:
        prepared: list[str] = []
        veto = RecordingPlugin(
            before=lambda event, edits: edits.preempt(5),
            prepare=lambda event, api: prepared.append("veto"),
        )
        dependent = RecordingPlugin(
            prepare=lambda event, api: prepared.append("dependent"),
        )

        result = self.run_application(
            self.make_application(veto, dependent),
            [],
        )

        self.assertEqual(result, 5)
        self.assertEqual(prepared, [])
        self.assertEqual(veto.prepare_events, [])
        self.assertEqual(dependent.prepare_events, [])
        self.assertEqual(len(veto.after_events), 1)
        self.assertEqual(len(dependent.after_events), 1)

    def test_help_mode_preserves_arguments_and_ignores_edits(self) -> None:
        def edit_help(event, edits) -> None:
            self.assertEqual(event.mode, CallMode.HELP)
            edits.remove_range(0, len(event.wrapper_args))
            edits.add("--changed")
            edits.preempt(9)

        plugin = RecordingPlugin(
            help_text="  --plugin VALUE   Plugin option", before=edit_help
        )
        engulf = self.make_application(plugin)
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            result = self.run_application(
                engulf,
                ["subcommand", "--help", "topic"],
                ENGULF_TEST_EXIT="4",
            )

        self.assertEqual(result, 4)
        self.assertEqual(self.recorded_args(), ["subcommand", "--help", "topic"])
        self.assertIn("Engulf plugin help:", output.getvalue())
        self.assertIn("\n  --plugin VALUE", output.getvalue())
        self.assertEqual(
            plugin.after_events[0].effective_args, ("subcommand", "--help", "topic")
        )

    def test_help_like_value_does_not_enter_help_mode(self) -> None:
        plugin = RecordingPlugin(before=lambda event, edits: edits.preempt(3))

        result = self.run_application(self.make_application(plugin), ["--help=topic"])

        self.assertEqual(result, 3)
        self.assertEqual(plugin.before_events[0].mode, CallMode.NORMAL)

    def test_argument_declarations_have_no_runtime_effect(self) -> None:
        class MetadataPlugin(RecordingPlugin):
            def register_arguments(self, registry, api) -> None:
                del api
                registry.option("--plugin", takes_value=True)

        engulf = self.make_application(MetadataPlugin())

        result = self.run_application(engulf, ["--plugin", "value"])

        self.assertEqual(result, 0)
        self.assertEqual(self.recorded_args(), ["--plugin", "value"])

    def test_binary_exit_code_is_returned(self) -> None:
        plugin = RecordingPlugin()

        result = self.run_application(
            self.make_application(plugin),
            [],
            ENGULF_TEST_EXIT="23",
        )

        self.assertEqual(result, 23)
        self.assertEqual(plugin.after_events[0].outcome.exit_code, 23)

    def test_signal_is_normalized(self) -> None:
        plugin = RecordingPlugin()

        result = self.run_application(
            self.make_application(plugin),
            [],
            ENGULF_TEST_SIGNAL=str(signal.SIGTERM),
        )

        self.assertEqual(result, 128 + signal.SIGTERM)
        self.assertEqual(plugin.after_events[0].outcome.kind, OutcomeKind.SIGNALED)
        self.assertEqual(plugin.after_events[0].outcome.signal, signal.SIGTERM)

    def test_direct_signals_are_forwarded_and_postprocessed(self) -> None:
        waiting_binary = self.directory / "waiting-command"
        waiting_binary.write_text(
            WAITING_BINARY.format(python=sys.executable),
            encoding="utf-8",
        )
        waiting_binary.chmod(0o755)
        (self.plugin_directory / "signal_plugin.py").write_text(
            SIGNAL_PLUGIN,
            encoding="utf-8",
        )

        workspace = Path(__file__).resolve().parents[2]
        source_paths = (
            workspace / "engulf-api" / "src",
            workspace / "engulf" / "src",
            workspace / "engulf-executable-wrapper-api" / "src",
            workspace / "engulf-executable-wrapper" / "src",
        )
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=signum.name):
                ready = self.directory / f"ready-{signum.name}"
                outcome = self.directory / f"outcome-{signum.name}.json"
                environment = os.environ.copy()
                environment.update(
                    {
                        "ENGULF_SIGNAL_BINARY": str(waiting_binary),
                        "ENGULF_SIGNAL_OUTCOME": str(outcome),
                        "ENGULF_SIGNAL_PLUGIN_DIR": str(self.plugin_directory),
                        "ENGULF_SIGNAL_READY": str(ready),
                        "PYTHONPATH": os.pathsep.join(
                            os.fspath(path) for path in source_paths
                        ),
                    }
                )
                wrapper = subprocess.Popen(
                    [sys.executable, "-c", SIGNAL_WRAPPER],
                    env=environment,
                    start_new_session=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                child_pid: int | None = None
                try:
                    deadline = time.monotonic() + 5.0
                    while not ready.exists():
                        if wrapper.poll() is not None:
                            stdout, stderr = wrapper.communicate()
                            self.fail(
                                "wrapper exited before child readiness: "
                                f"stdout={stdout!r}, stderr={stderr!r}"
                            )
                        if time.monotonic() >= deadline:
                            self.fail("timed out waiting for wrapped child")
                        time.sleep(0.01)

                    child_pid_text, child_group_text = ready.read_text(
                        encoding="utf-8"
                    ).split()
                    child_pid = int(child_pid_text)
                    self.assertEqual(int(child_group_text), os.getpgid(wrapper.pid))

                    os.kill(wrapper.pid, signum)
                    stdout, stderr = wrapper.communicate(timeout=5.0)
                finally:
                    if wrapper.poll() is None:
                        wrapper.kill()
                        wrapper.wait()
                    if child_pid is not None:
                        try:
                            os.kill(child_pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass

                self.assertEqual(stdout, "")
                self.assertEqual(stderr, "")
                self.assertEqual(wrapper.returncode, 128 + signum)
                self.assertEqual(
                    json.loads(outcome.read_text(encoding="utf-8")),
                    {
                        "kind": OutcomeKind.SIGNALED.value,
                        "exit_code": 128 + signum,
                        "signal": signum,
                    },
                )

    def test_signal_handlers_are_restored_after_execution(self) -> None:
        previous_term = signal.getsignal(signal.SIGTERM)
        previous_hup = signal.getsignal(signal.SIGHUP)

        def custom_term(signum, frame) -> None:
            del signum, frame

        signal.signal(signal.SIGTERM, custom_term)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        try:
            result = self.run_application(self.make_application(RecordingPlugin()), [])

            self.assertEqual(result, 0)
            self.assertIs(signal.getsignal(signal.SIGTERM), custom_term)
            self.assertEqual(signal.getsignal(signal.SIGHUP), signal.SIG_IGN)
        finally:
            signal.signal(signal.SIGTERM, previous_term)
            signal.signal(signal.SIGHUP, previous_hup)

    def test_path_lookup(self) -> None:
        plugin = RecordingPlugin()
        path = f"{self.directory}{os.pathsep}{os.environ.get('PATH', '')}"

        with patch.dict(os.environ, {"PATH": path}, clear=False):
            result = self.run_application(
                self.make_application(plugin, binary=self.binary.name), ["found"]
            )

        self.assertEqual(result, 0)
        self.assertEqual(self.recorded_args(), ["found"])

    def test_missing_binary_returns_127_and_emits_after(self) -> None:
        plugin = RecordingPlugin()
        error_output = io.StringIO()

        with contextlib.redirect_stderr(error_output):
            result = self.make_application(
                plugin, binary="engulf-command-that-does-not-exist"
            ).run([])

        self.assertEqual(result, 127)
        self.assertEqual(plugin.after_events[0].outcome.kind, OutcomeKind.SPAWN_FAILED)
        self.assertIn("command not found", error_output.getvalue())

    def test_non_executable_binary_returns_126(self) -> None:
        self.binary.chmod(0o644)
        plugin = RecordingPlugin()

        with contextlib.redirect_stderr(io.StringIO()):
            result = self.make_application(plugin).run([])

        self.assertEqual(result, 126)
        self.assertEqual(plugin.after_events[0].outcome.exit_code, 126)

    def test_analysis_exception_stops_goal_and_returns_framework_failure(self) -> None:
        def fail(event, edits) -> None:
            raise RuntimeError("before failed")

        first = RecordingPlugin(before=fail)
        second = RecordingPlugin()

        with contextlib.redirect_stderr(io.StringIO()):
            result = self.make_application(first, second).run([])

        self.assertEqual(result, FRAMEWORK_ERROR_EXIT)
        self.assertEqual(len(first.before_events), 1)
        self.assertEqual(len(second.before_events), 0)
        self.assertEqual(len(first.after_events), 0)
        self.assertEqual(len(second.after_events), 0)
        self.assertFalse(self.record.exists())

    def test_after_exception_stops_after_phase_and_returns_70(self) -> None:
        def fail(event, api) -> None:
            raise RuntimeError("after failed")

        first = RecordingPlugin(after=fail)
        second = RecordingPlugin()

        with contextlib.redirect_stderr(io.StringIO()):
            result = self.run_application(self.make_application(first, second), [])

        self.assertEqual(result, FRAMEWORK_ERROR_EXIT)
        self.assertEqual(len(first.after_events), 1)
        self.assertEqual(len(second.after_events), 0)
        self.assertTrue(self.record.exists())

    def test_invalid_programmatic_arguments_return_70(self) -> None:
        plugin = RecordingPlugin()
        with contextlib.redirect_stderr(io.StringIO()):
            result = self.make_application(plugin).run(  # type: ignore[list-item]
                ["valid", 3]
            )

        self.assertEqual(result, FRAMEWORK_ERROR_EXIT)
        self.assertEqual(plugin.before_events, [])


if __name__ == "__main__":
    unittest.main()
