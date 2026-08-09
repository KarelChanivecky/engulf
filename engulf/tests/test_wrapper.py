from __future__ import annotations

import contextlib
import io
import json
import os
import signal
import sys
import tempfile
import unittest
from itertools import count
from pathlib import Path
from unittest.mock import patch

from engulf_api import (
    AdditionPlacement,
    CallMode,
    OutcomeKind,
    Plugin,
)

from engulf import FRAMEWORK_ERROR_EXIT, Engulf

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

_plugin_ids = count()


class RecordingPlugin(Plugin):
    def __init__(
        self,
        *,
        plugin_id: str | None = None,
        priority: int = 50,
        help_text: str = "",
        before=None,
        after=None,
    ) -> None:
        self.plugin_id = plugin_id or f"tests.wrapper.plugin{next(_plugin_ids)}"
        self.priority = priority
        self.help_text = help_text
        self.before_action = before
        self.after_action = after
        self.before_events = []
        self.after_events = []

    def help(self) -> str:
        return self.help_text

    def before_call(self, event, api) -> None:
        self.before_events.append(event)
        if self.before_action is not None:
            self.before_action(event, api)

    def after_call(self, event, api) -> None:
        self.after_events.append(event)
        if self.after_action is not None:
            self.after_action(event, api)


class EngulfTestCase(unittest.TestCase):
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

    def make_engulf(
        self,
        *plugins: Plugin,
        binary: str | os.PathLike[str] | None = None,
    ) -> Engulf:
        with patch(
            "engulf.wrapper.load_directory_plugins", return_value=tuple(plugins)
        ):
            return Engulf(
                binary or self.binary,
                "engulf-lifecycle-tests",
                plugin_dir=self.plugin_directory,
                discover_installed=False,
            )

    def run_engulf(self, engulf: Engulf, args: list[str], **environment: str) -> int:
        values = {"ENGULF_TEST_RECORD": str(self.record), **environment}
        with patch.dict(os.environ, values, clear=False):
            return engulf.run(args)

    def recorded_args(self) -> list[str]:
        return json.loads(self.record.read_text(encoding="utf-8"))

    def test_passes_arguments_and_emits_events(self) -> None:
        plugin = RecordingPlugin()
        engulf = self.make_engulf(plugin)

        result = self.run_engulf(engulf, ["one", "two words", "--flag=value"])

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
        engulf = self.make_engulf(*plugins)
        original = ["keep", "drop", "--", "tail"]

        result = self.run_engulf(engulf, original)

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
        engulf = self.make_engulf(plugin)

        result = self.run_engulf(engulf, ["--same", "value"])

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
        engulf = self.make_engulf(*plugins)

        result = self.run_engulf(engulf, ["not-executed"])

        self.assertEqual(result, 7)
        self.assertEqual(calls, ["zero", "seven", "nine"])
        self.assertFalse(self.record.exists())
        for plugin in plugins:
            self.assertEqual(plugin.after_events[0].outcome.kind, OutcomeKind.PREEMPTED)
            self.assertEqual(plugin.after_events[0].outcome.exit_code, 7)

    def test_priority_orders_activation_and_preserves_ties(self) -> None:
        calls = []

        class OrderedPlugin(RecordingPlugin):
            def __init__(self, name: str, priority: int) -> None:
                super().__init__(priority=priority)
                self.name = name

            def register_arguments(self, registry) -> None:
                calls.append((self.name, "arguments"))

            def register_completions(self, registry) -> None:
                calls.append((self.name, "completions"))

            def before_call(self, event, api) -> None:
                calls.append((self.name, "before"))
                super().before_call(event, api)

            def after_call(self, event, api) -> None:
                calls.append((self.name, "after"))
                super().after_call(event, api)

        plugins = [
            OrderedPlugin("low", -5),
            OrderedPlugin("equal-first", 10),
            OrderedPlugin("high", 100),
            OrderedPlugin("equal-second", 10),
        ]

        engulf = self.make_engulf(*plugins)
        result = self.run_engulf(engulf, [])

        self.assertEqual(result, 0)
        self.assertEqual(
            [plugin.name for plugin in engulf.plugins],
            ["high", "equal-first", "equal-second", "low"],
        )
        self.assertEqual(
            calls,
            [
                ("high", "arguments"),
                ("high", "completions"),
                ("equal-first", "arguments"),
                ("equal-first", "completions"),
                ("equal-second", "arguments"),
                ("equal-second", "completions"),
                ("low", "arguments"),
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

        result = self.run_engulf(self.make_engulf(low, high), [])

        self.assertEqual(result, 9)
        self.assertEqual(calls, ["high", "low"])

    def test_zero_preemption_skips_binary(self) -> None:
        plugin = RecordingPlugin(before=lambda event, edits: edits.preempt(0))

        result = self.run_engulf(self.make_engulf(plugin), [])

        self.assertEqual(result, 0)
        self.assertFalse(self.record.exists())

    def test_help_mode_preserves_arguments_and_ignores_edits(self) -> None:
        def edit_help(event, edits) -> None:
            self.assertEqual(event.mode, CallMode.HELP)
            edits.remove_range(0, len(event.wrapper_args))
            edits.add("--changed")
            edits.preempt(9)

        plugin = RecordingPlugin(
            help_text="  --plugin VALUE   Plugin option", before=edit_help
        )
        engulf = self.make_engulf(plugin)
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            result = self.run_engulf(
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

        result = self.run_engulf(self.make_engulf(plugin), ["--help=topic"])

        self.assertEqual(result, 3)
        self.assertEqual(plugin.before_events[0].mode, CallMode.NORMAL)

    def test_argument_declarations_have_no_runtime_effect(self) -> None:
        class MetadataPlugin(RecordingPlugin):
            def register_arguments(self, registry) -> None:
                registry.option("--plugin", takes_value=True)

        engulf = self.make_engulf(MetadataPlugin())

        result = self.run_engulf(engulf, ["--plugin", "value"])

        self.assertEqual(result, 0)
        self.assertEqual(self.recorded_args(), ["--plugin", "value"])

    def test_binary_exit_code_is_returned(self) -> None:
        plugin = RecordingPlugin()

        result = self.run_engulf(
            self.make_engulf(plugin),
            [],
            ENGULF_TEST_EXIT="23",
        )

        self.assertEqual(result, 23)
        self.assertEqual(plugin.after_events[0].outcome.exit_code, 23)

    def test_signal_is_normalized(self) -> None:
        plugin = RecordingPlugin()

        result = self.run_engulf(
            self.make_engulf(plugin),
            [],
            ENGULF_TEST_SIGNAL=str(signal.SIGTERM),
        )

        self.assertEqual(result, 128 + signal.SIGTERM)
        self.assertEqual(plugin.after_events[0].outcome.kind, OutcomeKind.SIGNALED)
        self.assertEqual(plugin.after_events[0].outcome.signal, signal.SIGTERM)

    def test_path_lookup(self) -> None:
        plugin = RecordingPlugin()
        path = f"{self.directory}{os.pathsep}{os.environ.get('PATH', '')}"

        with patch.dict(os.environ, {"PATH": path}, clear=False):
            result = self.run_engulf(
                self.make_engulf(plugin, binary=self.binary.name), ["found"]
            )

        self.assertEqual(result, 0)
        self.assertEqual(self.recorded_args(), ["found"])

    def test_missing_binary_returns_127_and_emits_after(self) -> None:
        plugin = RecordingPlugin()
        error_output = io.StringIO()

        with contextlib.redirect_stderr(error_output):
            result = self.make_engulf(
                plugin, binary="engulf-command-that-does-not-exist"
            ).run([])

        self.assertEqual(result, 127)
        self.assertEqual(plugin.after_events[0].outcome.kind, OutcomeKind.SPAWN_FAILED)
        self.assertIn("command not found", error_output.getvalue())

    def test_non_executable_binary_returns_126(self) -> None:
        self.binary.chmod(0o644)
        plugin = RecordingPlugin()

        with contextlib.redirect_stderr(io.StringIO()):
            result = self.make_engulf(plugin).run([])

        self.assertEqual(result, 126)
        self.assertEqual(plugin.after_events[0].outcome.exit_code, 126)

    def test_before_exception_stops_before_phase_but_emits_after(self) -> None:
        def fail(event, edits) -> None:
            raise RuntimeError("before failed")

        first = RecordingPlugin(before=fail)
        second = RecordingPlugin()

        with contextlib.redirect_stderr(io.StringIO()):
            result = self.make_engulf(first, second).run([])

        self.assertEqual(result, FRAMEWORK_ERROR_EXIT)
        self.assertEqual(len(first.before_events), 1)
        self.assertEqual(len(second.before_events), 0)
        self.assertEqual(len(first.after_events), 1)
        self.assertEqual(len(second.after_events), 1)
        self.assertEqual(
            first.after_events[0].outcome.kind, OutcomeKind.FRAMEWORK_FAILED
        )
        self.assertFalse(self.record.exists())

    def test_after_exception_stops_after_phase_and_returns_70(self) -> None:
        def fail(event, api) -> None:
            raise RuntimeError("after failed")

        first = RecordingPlugin(after=fail)
        second = RecordingPlugin()

        with contextlib.redirect_stderr(io.StringIO()):
            result = self.run_engulf(self.make_engulf(first, second), [])

        self.assertEqual(result, FRAMEWORK_ERROR_EXIT)
        self.assertEqual(len(first.after_events), 1)
        self.assertEqual(len(second.after_events), 0)
        self.assertTrue(self.record.exists())

    def test_invalid_programmatic_arguments_return_70(self) -> None:
        plugin = RecordingPlugin()
        with contextlib.redirect_stderr(io.StringIO()):
            result = self.make_engulf(plugin).run(  # type: ignore[list-item]
                ["valid", 3]
            )

        self.assertEqual(result, FRAMEWORK_ERROR_EXIT)
        self.assertEqual(plugin.before_events, [])


if __name__ == "__main__":
    unittest.main()
