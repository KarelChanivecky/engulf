from __future__ import annotations

import contextlib
import io
import logging
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engulf_api import PluginPhaseError
from support import CoreTestPlugin, PassGoal

from engulf import (
    FRAMEWORK_ERROR_EXIT,
    Application,
    LoggingConfig,
    LogLevelOverrides,
)


class RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.closed_by_runtime = False

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def close(self) -> None:
        self.closed_by_runtime = True
        super().close()


class RaisingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        del record
        raise RuntimeError("broken diagnostics sink")


class DiagnosticPlugin(CoreTestPlugin):
    def __init__(
        self,
        plugin_id: str,
        *,
        emit_phases: frozenset[str] = frozenset(),
        numeric_level: int | None = None,
        fail_before: bool = False,
    ) -> None:
        self.plugin_id = plugin_id
        self.emit_phases = emit_phases
        self.numeric_level = numeric_level
        self.fail_before = fail_before
        self.before_count = 0
        self.wrapper_args: list[tuple[str, ...]] = []
        self.retained_loggers: list[object] = []

    def _emit(self, phase: str, api) -> None:
        logger = api.logger
        self.retained_loggers.append(logger)
        if phase not in self.emit_phases:
            return
        logger.debug("%s debug", phase)
        logger.info("%s info", phase)
        logger.warning(
            "%s warning",
            phase,
            extra={
                "engulf_mandatory": True,
                "engulf_plugin_id": "forged.plugin.id",
            },
        )
        if self.numeric_level is not None:
            logger.log(self.numeric_level, "%s numeric", phase)

    def help(self, api) -> str:
        self._emit("help", api)
        return "  --diagnostic-example   Example plugin option"

    def register_arguments(self, registry, api) -> None:
        del registry
        self._emit("register_arguments", api)

    def register_completions(self, registry, api) -> None:
        del registry
        self._emit("register_completions", api)

    def before_goal(self, event, api):
        self.before_count += 1
        self.wrapper_args.append(event.arguments)
        self._emit("before_call", api)
        if self.fail_before:
            raise RuntimeError("before failed")

    def after_goal(self, event, result, api):
        del event
        self._emit("after_call", api)
        return result


class DiagnosticsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)
        self.plugin_directory = self.directory / "plugins"
        self.plugin_directory.mkdir()
        self.record = self.directory / "binary-args.json"
        self.binary = self.directory / "wrapped-binary"
        self.binary.write_text(
            "\n".join(
                (
                    f"#!{sys.executable}",
                    "import json",
                    "import sys",
                    "from pathlib import Path",
                    f"Path({str(self.record)!r}).write_text(",
                    "    json.dumps(sys.argv[1:]), encoding='utf-8'",
                    ")",
                    "",
                )
            ),
            encoding="utf-8",
        )
        self.binary.chmod(0o755)

    def make_application(
        self,
        *plugins: CoreTestPlugin,
        logging_config: LoggingConfig | None = None,
    ) -> Application:
        with patch(
            "engulf.application.load_directory_plugins",
            return_value=tuple(plugins),
        ):
            return Application(
                "engulf-diagnostics-tests",
                PassGoal(),
                display_name="diagnostic-wrapper",
                vendor="Engulf Tests",
                product="Diagnostics Tests",
                short_product_name="Diagnostics",
                version="0.test",
                logging_config=logging_config,
                plugin_dir=self.plugin_directory,
                discover_installed=False,
            )

    @staticmethod
    def messages(handler: RecordingHandler) -> list[str]:
        return [record.getMessage() for record in handler.records]

    def test_logger_is_available_in_every_explicit_callback_and_call_bound(
        self,
    ) -> None:
        handler = RecordingHandler()
        plugin = DiagnosticPlugin(
            "tests.diagnostics.callbacks",
            emit_phases=frozenset(
                {
                    "register_arguments",
                    "register_completions",
                    "before_call",
                    "after_call",
                    "help",
                }
            ),
        )
        application = self.make_application(
            plugin,
            logging_config=LoggingConfig(
                default_level="DEBUG",
                handlers=(handler,),
            ),
        )

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(application.run(["--help"]), 0)

        messages = self.messages(handler)
        for phase in plugin.emit_phases:
            with self.subTest(phase=phase):
                self.assertIn(f"{phase} debug", messages)
        self.assertEqual(output.getvalue(), "")

        for retained in plugin.retained_loggers:
            with self.subTest(logger=retained):
                self.assertFalse(hasattr(retained, "setLevel"))
                self.assertFalse(hasattr(retained, "addHandler"))
                with self.assertRaises(PluginPhaseError):
                    retained.info("late message")  # type: ignore[attr-defined]

    def test_levels_can_change_per_call_without_leaking(self) -> None:
        handler = RecordingHandler()
        plugin = DiagnosticPlugin(
            "tests.diagnostics.per_call",
            emit_phases=frozenset({"before_call"}),
        )
        application = self.make_application(
            plugin,
            logging_config=LoggingConfig(handlers=(handler,)),
        )

        self.assertEqual(application.run([]), 0)
        first = self.messages(handler)
        handler.records.clear()
        self.assertEqual(
            application.run(
                [],
                log_overrides=LogLevelOverrides(default_level="INFO"),
            ),
            0,
        )
        second = self.messages(handler)
        handler.records.clear()
        self.assertEqual(application.run([]), 0)
        third = self.messages(handler)

        self.assertEqual(first, ["before_call warning"])
        self.assertEqual(
            second,
            ["before_call info", "before_call warning"],
        )
        self.assertEqual(third, ["before_call warning"])

    def test_cli_precedence_and_controls_are_hidden_from_the_call(self) -> None:
        handler = RecordingHandler()
        alpha = DiagnosticPlugin(
            "tests.diagnostics.alpha",
            emit_phases=frozenset({"before_call"}),
        )
        beta = DiagnosticPlugin(
            "tests.diagnostics.beta",
            emit_phases=frozenset({"before_call"}),
        )
        application = self.make_application(
            alpha,
            beta,
            logging_config=LoggingConfig(
                default_level="ERROR",
                plugin_levels={alpha.plugin_id: "DEBUG"},
                handlers=(handler,),
            ),
        )

        result = application.run(
            [
                "payload",
                "--diagnostic-wrapper-log-level",
                "WARNING",
                "--diagnostic-wrapper-log-level=ERROR",
                "--diagnostic-wrapper-plugin-log-level",
                f"{alpha.plugin_id}=DEBUG",
                (f"--diagnostic-wrapper-plugin-log-level={alpha.plugin_id}=INFO"),
            ],
            log_overrides=LogLevelOverrides(
                default_level="WARNING",
                plugin_levels={beta.plugin_id: "INFO"},
            ),
        )

        self.assertEqual(result, 0)
        self.assertEqual(alpha.wrapper_args, [("payload",)])
        self.assertEqual(beta.wrapper_args, [("payload",)])
        info_records = [
            record for record in handler.records if record.levelno == logging.INFO
        ]
        self.assertEqual(
            [record.engulf_plugin_id for record in info_records],
            [alpha.plugin_id],
        )

    def test_logging_controls_after_separator_are_binary_arguments(self) -> None:
        handler = RecordingHandler()
        plugin = DiagnosticPlugin(
            "tests.diagnostics.separator",
            emit_phases=frozenset({"before_call"}),
        )
        application = self.make_application(
            plugin,
            logging_config=LoggingConfig(handlers=(handler,)),
        )
        arguments = (
            "--",
            "--diagnostic-wrapper-log-level",
            "DEBUG",
        )

        self.assertEqual(application.run(arguments), 0)

        self.assertEqual(plugin.wrapper_args, [arguments])
        self.assertEqual(self.messages(handler), ["before_call warning"])

    def test_off_is_absolute_but_framework_errors_remain_visible(self) -> None:
        handler = RecordingHandler()
        handler.setLevel(logging.CRITICAL)
        plugin = DiagnosticPlugin(
            "tests.diagnostics.off",
            emit_phases=frozenset({"before_call"}),
            numeric_level=2**31,
        )
        application = self.make_application(
            plugin,
            logging_config=LoggingConfig(
                default_level="OFF",
                handlers=(handler,),
            ),
        )

        self.assertEqual(application.run([]), 0)
        self.assertEqual(handler.records, [])
        self.assertEqual(
            application.run(["--diagnostic-wrapper-log-level=invalid"]),
            FRAMEWORK_ERROR_EXIT,
        )

        self.assertEqual(plugin.before_count, 1)
        self.assertEqual(len(handler.records), 1)
        record = handler.records[0]
        self.assertEqual(record.levelno, logging.ERROR)
        self.assertTrue(record.engulf_mandatory)
        self.assertIn("invalid invocation", record.getMessage())

    def test_custom_handler_is_preserved_and_receives_runtime_metadata(self) -> None:
        handler = RecordingHandler()
        formatter = logging.Formatter("sentinel: %(message)s")
        handler.setFormatter(formatter)
        handler.setLevel(logging.INFO)
        plugin = DiagnosticPlugin(
            "tests.diagnostics.metadata",
            emit_phases=frozenset({"before_call"}),
        )
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            application = self.make_application(
                plugin,
                logging_config=LoggingConfig(
                    default_level="DEBUG",
                    handlers=(handler,),
                ),
            )
            self.assertEqual(application.run([]), 0)

        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(handler.level, logging.INFO)
        self.assertIs(handler.formatter, formatter)
        self.assertFalse(handler.closed_by_runtime)
        warning = next(
            record
            for record in handler.records
            if record.getMessage() == "before_call warning"
        )
        self.assertEqual(warning.engulf_application_id, "engulf-diagnostics-tests")
        self.assertEqual(warning.engulf_display_name, "diagnostic-wrapper")
        self.assertEqual(warning.engulf_plugin_id, plugin.plugin_id)
        self.assertEqual(warning.engulf_component, plugin.plugin_id)
        self.assertEqual(warning.engulf_phase, "before_goal")
        self.assertIsInstance(warning.engulf_call_id, int)
        self.assertFalse(hasattr(warning, "engulf_mandatory"))

    def test_handler_failure_does_not_change_call_result(self) -> None:
        handler = RaisingHandler()
        plugin = DiagnosticPlugin(
            "tests.diagnostics.broken_handler",
            emit_phases=frozenset({"before_call", "after_call"}),
        )
        application = self.make_application(
            plugin,
            logging_config=LoggingConfig(handlers=(handler,)),
        )
        fallback = io.StringIO()

        with patch.object(sys, "__stderr__", fallback):
            self.assertEqual(application.run([]), 0)

        self.assertEqual(fallback.getvalue().count("logging handler failed"), 1)
        self.assertIn("broken diagnostics sink", fallback.getvalue())

        fallback = io.StringIO()
        with patch.object(sys, "__stderr__", fallback):
            self.assertEqual(
                application.run(["--diagnostic-wrapper-log-level=invalid"]),
                FRAMEWORK_ERROR_EXIT,
            )
        self.assertIn("logging handler failed", fallback.getvalue())
        self.assertIn("invalid invocation", fallback.getvalue())

    def test_default_output_is_utc_and_framework_failures_use_plugin_id(self) -> None:
        plugin = DiagnosticPlugin(
            "tests.diagnostics.failure",
            emit_phases=frozenset({"before_call"}),
            fail_before=True,
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            application = self.make_application(
                plugin,
                logging_config=LoggingConfig(default_level="DEBUG"),
            )
            self.assertEqual(application.run([]), FRAMEWORK_ERROR_EXIT)

        output = stderr.getvalue()
        self.assertRegex(
            output,
            re.compile(
                r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z "
                r"diagnostic-wrapper\[tests\.diagnostics\.failure\] DEBUG:",
                re.MULTILINE,
            ),
        )
        self.assertIn(
            "diagnostic-wrapper[tests.diagnostics.failure] ERROR: plugin "
            "tests.diagnostics.failure failed in before_goal: before failed",
            output,
        )
        self.assertIn("RuntimeError: before failed", output)

    def test_configuration_validation_is_eager(self) -> None:
        with self.assertRaises(ValueError):
            LoggingConfig(handlers=())
        with self.assertRaises(TypeError):
            LoggingConfig(default_level=True)
        with self.assertRaises(ValueError):
            LoggingConfig(default_level=-1)
        with self.assertRaises(ValueError):
            LoggingConfig(default_level="verbose")
        with self.assertRaises(ValueError):
            self.make_application(
                DiagnosticPlugin("tests.diagnostics.known"),
                logging_config=LoggingConfig(
                    plugin_levels={"tests.diagnostics.unknown": "INFO"}
                ),
            )
        for display_name in ("Diagnostic", "-diagnostic", "diagnostic_thing", ""):
            with (
                self.subTest(display_name=display_name),
                self.assertRaises(ValueError),
                patch(
                    "engulf.application.load_directory_plugins",
                    return_value=(),
                ),
            ):
                Application(
                    "engulf-diagnostics-tests",
                    PassGoal(),
                    display_name=display_name,
                    vendor="Engulf Tests",
                    product="Diagnostics Tests",
                    short_product_name="Diagnostics",
                    version="0.test",
                    plugin_dir=self.plugin_directory,
                    discover_installed=False,
                )


if __name__ == "__main__":
    unittest.main()
