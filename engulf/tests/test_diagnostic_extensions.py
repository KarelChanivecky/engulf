from __future__ import annotations

import io
import os
import unittest
from importlib.metadata import EntryPoint
from pathlib import Path
from unittest.mock import patch

from engulf._diagnostic_worker import _diagnostic_extension
from engulf.diagnostic_extensions import (
    DiagnosticIsolationConfig,
    _bubblewrap_command,
    _open_readonly_mount_sources,
    diagnostic_entry_point_group,
    diagnostic_trigger_entry_point_group,
)
from engulf_api import DiagnosticContribution, GoalResultStatus
from support import TEST_GOAL_REQUIREMENT, PassGoal

from engulf import Application


class _Runner:
    def __init__(self, *, fail_id: str | None = None) -> None:
        self.fail_id = fail_id
        self.calls: list[str] = []

    def run(
        self,
        diagnostic,
        request,
        active_plugins,
        plugin_executions,
        diagnostic_extensions,
        elevated,
    ) -> DiagnosticContribution:
        del active_plugins, plugin_executions, diagnostic_extensions, elevated
        diagnostic_id = diagnostic.descriptor.diagnostic_id
        self.calls.append(diagnostic_id)
        if diagnostic_id == self.fail_id:
            raise RuntimeError("worker failed")
        self.assert_sanitized(request)
        exit_code = 9 if diagnostic_id.endswith("beta") else 0
        return DiagnosticContribution(stdout=f"{diagnostic_id}\n", exit_code=exit_code)

    @staticmethod
    def assert_sanitized(request) -> None:
        if hasattr(request, "environment") or hasattr(request, "cwd"):
            raise AssertionError("diagnostic request exposed process context")


class DiagnosticExtensionTestCase(unittest.TestCase):
    def test_worker_restores_immutable_trigger_tuples_from_json(self) -> None:
        extension = _diagnostic_extension(
            {
                "diagnostic_id": "tests.diagnostic.protocol",
                "triggers": ["--diagnose"],
                "distribution": "tests-diagnostic",
                "version": "1",
                "target": "tests_diagnostic:plugin",
                "available": True,
                "unavailable_reason": None,
            }
        )

        self.assertEqual(extension.triggers, ("--diagnose",))

    def test_bubblewrap_mounts_dynamic_loader_paths_for_python(self) -> None:
        entry_point = EntryPoint(
            "tests.diagnostic.runtime",
            "never_import_runtime:plugin",
            diagnostic_entry_point_group(
                TEST_GOAL_REQUIREMENT.goal_id,
                TEST_GOAL_REQUIREMENT.api_major,
            ),
        )

        command = _bubblewrap_command(entry_point, DiagnosticIsolationConfig())

        self.assertTrue(command[0].endswith("/unshare"))
        self.assertIn("--net", command)
        self.assertNotIn("--unshare-net", command)
        self.assertIn("/usr", command)
        for path in ("/lib", "/lib64"):
            if Path(path).exists():
                self.assertIn(path, command)

        prepared, descriptors = _open_readonly_mount_sources(command)
        try:
            self.assertTrue(descriptors)
            for descriptor in descriptors:
                self.assertIn(f"/proc/self/fd/{descriptor}", prepared)
                self.assertTrue(Path(f"/proc/self/fd/{descriptor}").exists())
        finally:
            for descriptor in descriptors:
                os.close(descriptor)

    def make_application(self, *, available: bool = True) -> Application:
        catalog_group = diagnostic_entry_point_group(
            TEST_GOAL_REQUIREMENT.goal_id, TEST_GOAL_REQUIREMENT.api_major
        )
        trigger_group = diagnostic_trigger_entry_point_group(
            TEST_GOAL_REQUIREMENT.goal_id, TEST_GOAL_REQUIREMENT.api_major
        )
        entries = {
            catalog_group: (
                EntryPoint(
                    "tests.diagnostic.beta", "never_import_beta:plugin", catalog_group
                ),
                EntryPoint(
                    "tests.diagnostic.alpha", "never_import_alpha:plugin", catalog_group
                ),
            ),
            trigger_group: (
                EntryPoint(
                    "--diagnose-beta", "never_import_beta:plugin", trigger_group
                ),
                EntryPoint(
                    "--diagnose-alpha", "never_import_alpha:plugin", trigger_group
                ),
            ),
        }

        def discover(*, group: str):
            return entries.get(group, ())

        availability = (True, None) if available else (False, "test unavailable")
        with (
            patch("engulf.diagnostic_extensions.entry_points", side_effect=discover),
            patch(
                "engulf.diagnostic_extensions._isolation_available",
                return_value=availability,
            ),
        ):
            return Application(
                "tests.diagnostic.app",
                PassGoal(),
                display_name="diagnostic-app",
                vendor="Tests",
                product="Diagnostics",
                short_product_name="Diagnostics",
                version="1",
                discover_installed=True,
            )

    def test_matching_diagnostics_suppress_goal_and_aggregate_in_order(self) -> None:
        application = self.make_application()
        runner = _Runner()
        application._diagnostic_runner = runner  # type: ignore[attr-defined]
        output = io.StringIO()
        with patch("sys.stdout", output):
            result = application.invoke(("--diagnose-beta", "--diagnose-alpha"))

        self.assertIs(result.status, GoalResultStatus.DIAGNOSTIC)
        self.assertEqual(result.exit_code, 9)
        self.assertEqual(
            result.diagnostic_ids,
            ("tests.diagnostic.alpha", "tests.diagnostic.beta"),
        )
        self.assertEqual(runner.calls, list(result.diagnostic_ids))
        self.assertNotIn("never_import_alpha", __import__("sys").modules)
        self.assertEqual(application.invoke(("normal",)).value, ("normal",))
        application.close()

    def test_worker_failure_does_not_stop_later_diagnostics(self) -> None:
        application = self.make_application()
        runner = _Runner(fail_id="tests.diagnostic.alpha")
        application._diagnostic_runner = runner  # type: ignore[attr-defined]
        with patch("sys.stdout", io.StringIO()):
            result = application.invoke(("--diagnose-alpha", "--diagnose-beta"))
        self.assertIs(result.status, GoalResultStatus.FRAMEWORK_FAILED)
        self.assertEqual(
            runner.calls, ["tests.diagnostic.alpha", "tests.diagnostic.beta"]
        )
        application.close()

    def test_trigger_after_separator_is_normal_and_disabled_trigger_is_rejected(
        self,
    ) -> None:
        application = self.make_application(available=False)
        after_separator = application.invoke(("--", "--diagnose-alpha"))
        rejected = application.invoke(("--diagnose-alpha",))
        self.assertIs(after_separator.status, GoalResultStatus.COMPLETED)
        self.assertEqual(after_separator.value, ("--", "--diagnose-alpha"))
        self.assertIs(rejected.status, GoalResultStatus.FRAMEWORK_FAILED)
        self.assertEqual(rejected.exit_code, 70)
        application.close()


if __name__ == "__main__":
    unittest.main()
