from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import unittest
from dataclasses import asdict
from importlib.metadata import EntryPoint
from pathlib import Path
from unittest.mock import patch

from engulf._diagnostic_worker import _diagnostic_extension
from engulf.diagnostic_extensions import (
    DiagnosticIsolationConfig,
    _bubblewrap_command,
    _isolation_available,
    _open_readonly_mount_sources,
    _process_error_detail,
    _ProcessOutput,
    _run_bounded,
    _supports_ro_bind_fd,
    diagnostic_entry_point_group,
    diagnostic_trigger_entry_point_group,
)
from engulf_api import DiagnosticContribution, GoalResultStatus
from support import TEST_GOAL_REQUIREMENT, PassGoal

from engulf import Application


class _Runner:
    def __init__(
        self,
        *,
        available: bool = True,
        fail_id: str | None = None,
    ) -> None:
        self.available = available
        self.fail_id = fail_id
        self.probe_calls: list[str] = []
        self.calls: list[str] = []

    def probe(self, diagnostic) -> tuple[bool, str | None]:
        self.probe_calls.append(diagnostic.descriptor.diagnostic_id)
        if self.available:
            return True, None
        return False, "test unavailable"

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
                "available": None,
                "unavailable_reason": None,
            }
        )

        self.assertEqual(extension.triggers, ("--diagnose",))
        self.assertIsNone(extension.available)

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

        prepared, mount_sources = _open_readonly_mount_sources(command)
        try:
            self.assertTrue(mount_sources)
            self.assertNotIn("--ro-bind", prepared)
            self.assertNotIn("/proc/self/fd", " ".join(prepared))
            for descriptor, source in mount_sources:
                option_index = prepared.index(str(descriptor)) - 1
                self.assertEqual(prepared[option_index], "--ro-bind-fd")
                self.assertTrue(Path(f"/proc/self/fd/{descriptor}").exists())
                self.assertTrue(Path(source).is_dir())
        finally:
            for descriptor, _ in mount_sources:
                os.close(descriptor)

    def test_bubblewrap_capability_check_requires_fd_mount_support(self) -> None:
        unsupported = subprocess.CompletedProcess(
            ("bwrap", "--help"), 0, b"--ro-bind SRC DEST\n", b""
        )
        with patch(
            "engulf.diagnostic_extensions.subprocess.run", return_value=unsupported
        ):
            available, reason = _supports_ro_bind_fd("bwrap", timeout=1.0)

        self.assertFalse(available)
        self.assertIn("--ro-bind-fd", reason)

    def test_bubblewrap_errors_name_original_mount_source(self) -> None:
        result = _ProcessOutput(
            1,
            b"",
            b"bwrap: Can't find source path /proc/self/fd/4: Permission denied\n",
            ((4, "/private/runtime"),),
        )

        detail = _process_error_detail(result)

        self.assertIn("/private/runtime (mount fd 4)", detail)
        self.assertNotIn("/proc/self/fd/4", detail)

    def test_bubblewrap_error_mount_replacement_respects_fd_boundaries(self) -> None:
        result = _ProcessOutput(
            1,
            b"",
            b"bwrap: failed to mount /proc/self/fd/42\n",
            ((4, "/runtime-four"), (42, "/runtime-forty-two")),
        )

        detail = _process_error_detail(result)

        self.assertIn("/runtime-forty-two (mount fd 42)", detail)
        self.assertNotIn("/runtime-four (mount fd 4)2", detail)

    def test_invalid_readonly_mount_closes_already_opened_sources(self) -> None:
        command = [
            "bwrap",
            "--ro-bind",
            "/runtime",
            "/sandbox-runtime",
            "--ro-bind",
            "/missing-destination",
        ]
        with (
            patch("engulf.diagnostic_extensions.os.open", return_value=17),
            patch("engulf.diagnostic_extensions.os.close") as close,
            self.assertRaisesRegex(ValueError, "requires source and destination"),
        ):
            _open_readonly_mount_sources(command)

        close.assert_called_once_with(17)

    def test_worker_launch_failure_closes_readonly_mount_descriptors(self) -> None:
        with (
            patch(
                "engulf.diagnostic_extensions._open_readonly_mount_sources",
                return_value=(["bwrap"], ((17, "/runtime"),)),
            ),
            patch(
                "engulf.diagnostic_extensions.subprocess.Popen",
                side_effect=OSError("launch failed"),
            ),
            patch("engulf.diagnostic_extensions.os.close") as close,
            self.assertRaisesRegex(OSError, "launch failed"),
        ):
            _run_bounded(["bwrap"], b"{}", timeout=1.0, limit=1024)

        close.assert_called_once_with(17)

    @unittest.skipUnless(
        sys.platform == "linux" and shutil.which("bwrap") and shutil.which("unshare"),
        "Bubblewrap isolation tools are not installed",
    )
    def test_supported_host_runs_real_fd_mount_probe(self) -> None:
        entry_point = EntryPoint(
            "tests.diagnostic.runtime",
            "never_import_runtime:plugin",
            diagnostic_entry_point_group(
                TEST_GOAL_REQUIREMENT.goal_id,
                TEST_GOAL_REQUIREMENT.api_major,
            ),
        )
        config = DiagnosticIsolationConfig()
        supported, reason = _supports_ro_bind_fd(
            shutil.which("bwrap") or "bwrap", timeout=2.0
        )
        if not supported:
            self.skipTest(reason)

        payload = json.dumps(
            {"version": 1, "probe": True, "limits": asdict(config)},
            separators=(",", ":"),
        ).encode()
        try:
            result = _run_bounded(
                _bubblewrap_command(entry_point, config),
                payload,
                timeout=2.0,
                limit=config.protocol_limit_bytes,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            self.skipTest(f"host namespace isolation is unavailable: {error}")
        if result.returncode != 0:
            detail = _process_error_detail(result)
            namespace_failures = (
                "Operation not permitted",
                "No permissions to create new namespace",
                "unshare failed",
            )
            if any(message in detail for message in namespace_failures):
                self.skipTest(f"host namespace isolation is unavailable: {detail}")

        self.assertEqual(result.returncode, 0, _process_error_detail(result))
        self.assertEqual(json.loads(result.stdout), {"version": 1, "probe": "ok"})

    def test_isolation_rejects_bubblewrap_without_fd_mounts_before_probe(self) -> None:
        entry_point = EntryPoint(
            "tests.diagnostic.runtime",
            "never_import_runtime:plugin",
            diagnostic_entry_point_group(
                TEST_GOAL_REQUIREMENT.goal_id,
                TEST_GOAL_REQUIREMENT.api_major,
            ),
        )
        with (
            patch(
                "engulf.diagnostic_extensions.shutil.which", return_value="/bin/tool"
            ),
            patch(
                "engulf.diagnostic_extensions._supports_ro_bind_fd",
                return_value=(False, "Bubblewrap lacks required fd mounts"),
            ),
            patch("engulf.diagnostic_extensions._run_bounded") as run_bounded,
        ):
            available, reason = _isolation_available(
                DiagnosticIsolationConfig(), entry_point
            )

        self.assertFalse(available)
        self.assertEqual(reason, "Bubblewrap lacks required fd mounts")
        run_bounded.assert_not_called()

    def make_application(self) -> Application:
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

        def discover():
            return tuple(
                entry_point
                for group_entries in entries.values()
                for entry_point in group_entries
            )

        with (
            patch(
                "engulf.plugin_loader.entry_points",
                side_effect=discover,
            ) as snapshot,
            patch("engulf.diagnostic_extensions._isolation_available") as probe,
        ):
            application = Application(
                "tests.diagnostic.app",
                PassGoal(),
                display_name="diagnostic-app",
                vendor="Tests",
                product="Diagnostics",
                short_product_name="Diagnostics",
                version="1",
                discover_installed=True,
            )
        snapshot.assert_called_once_with()
        probe.assert_not_called()
        return application

    def test_construction_and_normal_invocation_do_not_probe_isolation(self) -> None:
        application = self.make_application()
        runner = _Runner()
        application._diagnostic_runner = runner  # type: ignore[attr-defined]
        self.assertTrue(
            all(item.available is None for item in application.diagnostic_extensions)
        )
        self.assertEqual(application.invoke(("normal",)).value, ("normal",))
        self.assertEqual(runner.probe_calls, [])
        application.close()

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
        self.assertEqual(runner.probe_calls, ["tests.diagnostic.alpha"])
        self.assertEqual(runner.calls, list(result.diagnostic_ids))
        self.assertTrue(
            all(item.available is True for item in application.diagnostic_extensions)
        )
        self.assertNotIn("never_import_alpha", __import__("sys").modules)

        with patch("sys.stdout", io.StringIO()):
            application.invoke(("--diagnose-alpha",))
        self.assertEqual(runner.probe_calls, ["tests.diagnostic.alpha"])
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
        application = self.make_application()
        runner = _Runner(available=False)
        application._diagnostic_runner = runner  # type: ignore[attr-defined]
        after_separator = application.invoke(("--", "--diagnose-alpha"))
        self.assertEqual(runner.probe_calls, [])
        rejected = application.invoke(("--diagnose-alpha",))
        self.assertIs(after_separator.status, GoalResultStatus.COMPLETED)
        self.assertEqual(after_separator.value, ("--", "--diagnose-alpha"))
        self.assertIs(rejected.status, GoalResultStatus.FRAMEWORK_FAILED)
        self.assertEqual(rejected.exit_code, 70)
        self.assertEqual(runner.probe_calls, ["tests.diagnostic.alpha"])
        self.assertEqual(runner.calls, [])
        rejected_again = application.invoke(("--diagnose-beta",))
        self.assertIs(rejected_again.status, GoalResultStatus.FRAMEWORK_FAILED)
        self.assertEqual(runner.probe_calls, ["tests.diagnostic.alpha"])
        self.assertEqual(runner.calls, [])
        self.assertTrue(
            all(item.available is False for item in application.diagnostic_extensions)
        )
        self.assertTrue(
            all(
                item.unavailable_reason == "test unavailable"
                for item in application.diagnostic_extensions
            )
        )
        application.close()


if __name__ == "__main__":
    unittest.main()
