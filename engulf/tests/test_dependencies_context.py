from __future__ import annotations

import contextlib
import importlib
import io
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from typing import cast
from unittest.mock import patch

from engulf_api import (
    ContextAccessError,
    ElevationRequirement,
    MissingContextError,
    PluginPhaseError,
    UnusedContextWarning,
)
from support import (
    ORDERING_FIXTURE_MODULE,
    CoreTestPlugin,
    PassGoal,
    ordering_entry_points,
    write_ordering_fixture,
)

from engulf import (
    FRAMEWORK_ERROR_EXIT,
    Application,
    PluginDependencyError,
    PluginPolicy,
)


class TestPlugin(CoreTestPlugin):
    __test__ = False

    def __init__(
        self,
        plugin_id: str,
        *,
        priority: int = 50,
        elevation_requirement: ElevationRequirement = ElevationRequirement.NONE,
        reads: frozenset[str] = frozenset(),
        writes: frozenset[str] = frozenset(),
        before=None,
        after=None,
        calls: list[str] | None = None,
    ) -> None:
        self.plugin_id = plugin_id
        self.priority = priority
        self.elevation_requirement = elevation_requirement
        self.context_reads = reads
        self.context_writes = writes
        self.before_action = before
        self.after_action = after
        self.calls = calls

    def help(self, api) -> str:
        del api
        return self.plugin_id

    def before_goal(self, event, api):
        if self.calls is not None:
            self.calls.append(f"{self.plugin_id}.before")
        if self.before_action is not None:
            self.before_action(event, api)

    def after_goal(self, event, result, api):
        if self.calls is not None:
            self.calls.append(f"{self.plugin_id}.after")
        if self.after_action is not None:
            self.after_action(event, api)
        return result


class DependencyAndContextTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.plugin_directory = Path(self.temporary_directory.name)
        self.fixture_directory = self.plugin_directory / "installed"
        self.fixture_directory.mkdir()
        self.addCleanup(sys.modules.pop, ORDERING_FIXTURE_MODULE, None)

    def make_installed_application(
        self,
        exports: tuple[str, ...],
        dependencies: dict[str, dict[str, str]] | None = None,
    ) -> Application:
        write_ordering_fixture(self.fixture_directory)
        entries = ordering_entry_points(exports, dependencies)
        with (
            patch("engulf.plugin_loader.entry_points", return_value=entries),
            patch.object(sys, "path", [str(self.fixture_directory), *sys.path]),
        ):
            self.fixture = importlib.import_module(ORDERING_FIXTURE_MODULE)
            self.fixture.calls.clear()
            return Application(
                "engulf-dependency-context-tests",
                PassGoal(),
                display_name="engulf-dependency-context-tests",
                vendor="Engulf Tests",
                product="Dependency Context Tests",
                short_product_name="Dependencies",
                version="0.test",
                plugin_policy=PluginPolicy.allow_all_except(()),
            )

    def make_application(self, *plugins: CoreTestPlugin) -> Application:
        with patch(
            "engulf.application.load_directory_plugins", return_value=tuple(plugins)
        ):
            return Application(
                "engulf-dependency-context-tests",
                PassGoal(),
                display_name="engulf-dependency-context-tests",
                vendor="Engulf Tests",
                product="Dependency Context Tests",
                short_product_name="Dependencies",
                version="0.test",
                plugin_dir=self.plugin_directory,
                discover_installed=False,
            )

    def test_default_dependency_order_is_middleware_shaped(self) -> None:
        app = self.make_installed_application(
            ("high", "low"),
            {"high": {"tests.order.low": "preprocess=before; postprocess=after"}},
        )

        result = app.run([])

        self.assertEqual(result, 0)
        self.assertEqual(
            [plugin.plugin_id for plugin in app.plugins],
            ["tests.order.low", "tests.order.high"],
        )
        self.assertEqual(
            [plugin.plugin_id for plugin in app.postprocess_plugins],
            ["tests.order.high", "tests.order.low"],
        )
        self.assertEqual(
            self.fixture.calls,
            [
                "tests.order.low.before",
                "tests.order.high.before",
                "tests.order.high.after",
                "tests.order.low.after",
            ],
        )

    def test_phase_constraints_are_independent(self) -> None:
        app = self.make_installed_application(
            ("high", "low"),
            {"high": {"tests.order.low": "preprocess=none; postprocess=before"}},
        )

        self.assertEqual(
            [plugin.plugin_id for plugin in app.plugins],
            ["tests.order.high", "tests.order.low"],
        )
        self.assertEqual(
            [plugin.plugin_id for plugin in app.postprocess_plugins],
            ["tests.order.low", "tests.order.high"],
        )

    def test_priority_applies_only_among_ready_plugins(self) -> None:
        app = self.make_installed_application(
            ("high", "mid", "low"),
            {"high": {"tests.order.low": "preprocess=before; postprocess=none"}},
        )

        self.assertEqual(
            [plugin.plugin_id for plugin in app.plugins],
            ["tests.order.mid", "tests.order.low", "tests.order.high"],
        )

    def test_dependency_on_an_uninstalled_plugin_is_rejected(self) -> None:
        with self.assertRaisesRegex(PluginDependencyError, "requires missing plugin"):
            self.make_installed_application(
                ("high",),
                {
                    "high": {
                        "tests.order.absent": "preprocess=before; postprocess=after"
                    }
                },
            )

    def test_rejects_self_dependency_and_duplicate_plugin_ids(self) -> None:
        with self.assertRaisesRegex(PluginDependencyError, "depend on itself"):
            self.make_installed_application(
                ("high",),
                {"high": {"tests.order.high": "preprocess=before; postprocess=after"}},
            )

        duplicate_a = TestPlugin("tests.invalid.duplicate")
        duplicate_b = TestPlugin("tests.invalid.duplicate")
        with self.assertRaisesRegex(PluginDependencyError, "duplicate plugin_id"):
            self.make_application(duplicate_a, duplicate_b)

    def test_reports_preprocess_and_postprocess_cycles(self) -> None:
        with self.assertRaisesRegex(
            PluginDependencyError, "preprocess plugin dependency cycle"
        ):
            self.make_installed_application(
                ("high", "low"),
                {
                    "high": {"tests.order.low": "preprocess=before; postprocess=none"},
                    "low": {"tests.order.high": "preprocess=before; postprocess=none"},
                },
            )

        with self.assertRaisesRegex(
            PluginDependencyError, "postprocess plugin dependency cycle"
        ):
            self.make_installed_application(
                ("high", "low"),
                {
                    "high": {"tests.order.low": "preprocess=none; postprocess=before"},
                    "low": {"tests.order.high": "preprocess=none; postprocess=before"},
                },
            )

    def test_rejects_invalid_identity_and_context_metadata(self) -> None:
        with self.assertRaisesRegex(PluginDependencyError, "dot-qualified"):
            self.make_application(TestPlugin("invalid"))

        invalid_context = TestPlugin(
            "tests.invalid.context", reads=frozenset({"NOT.qualified"})
        )
        with self.assertRaisesRegex(PluginDependencyError, "context identifier"):
            self.make_application(invalid_context)

        invalid_elevation = TestPlugin(
            "tests.invalid.elevation",
            elevation_requirement=cast(ElevationRequirement, "required"),
        )
        with self.assertRaisesRegex(PluginDependencyError, "elevation_requirement"):
            self.make_application(invalid_elevation)

    def test_context_persists_through_both_phases_and_resets_per_call(self) -> None:
        context_id = "tests.context.value"
        observed: list[object] = []

        def before(event, api) -> None:
            observed.append(api.get_context(context_id, "missing"))
            api.set_context(context_id, event.arguments)

        def after(event, api) -> None:
            observed.append(api.require_context(context_id))

        plugin = TestPlugin(
            "tests.context.lifecycle",
            reads=frozenset({context_id}),
            writes=frozenset({context_id}),
            before=before,
            after=after,
        )
        app = self.make_application(plugin)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.assertEqual(app.run(["first"]), 0)
            self.assertEqual(app.run(["second"]), 0)

        self.assertEqual(
            observed,
            ["missing", ("first",), "missing", ("second",)],
        )
        self.assertEqual(caught, [])

    def test_multiple_writers_overwrite_in_preprocess_order(self) -> None:
        context_id = "tests.context.overwrite"
        observed: list[object] = []
        first = TestPlugin(
            "tests.context.writer_one",
            priority=100,
            writes=frozenset({context_id}),
            before=lambda event, api: api.set_context(context_id, "one"),
        )
        second = TestPlugin(
            "tests.context.writer_two",
            priority=50,
            writes=frozenset({context_id}),
            before=lambda event, api: api.set_context(context_id, "two"),
        )
        reader = TestPlugin(
            "tests.context.reader",
            priority=0,
            reads=frozenset({context_id}),
            before=lambda event, api: observed.append(api.require_context(context_id)),
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = self.make_application(reader, second, first).run([])

        self.assertEqual(result, 0)
        self.assertEqual(observed, ["two"])
        self.assertEqual(caught, [])

    def test_warns_once_for_sorted_context_written_but_never_read(self) -> None:
        alpha = "tests.context.alpha"
        beta = "tests.context.beta"

        def write(event, api) -> None:
            api.set_context(beta, 2)
            api.set_context(alpha, 1)

        plugin = TestPlugin(
            "tests.context.unused",
            writes=frozenset({alpha, beta}),
            before=write,
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = self.make_application(plugin).run([])

        self.assertEqual(result, 0)
        self.assertEqual(len(caught), 1)
        self.assertIs(caught[0].category, UnusedContextWarning)
        self.assertIn(f"{alpha}, {beta}", str(caught[0].message))

    def test_missing_get_does_not_count_as_a_context_read(self) -> None:
        context_id = "tests.context.missing_get"

        def access(event, api) -> None:
            self.assertIsNone(api.get_context(context_id))
            api.set_context(context_id, "later")

        plugin = TestPlugin(
            "tests.context.missing_reader",
            reads=frozenset({context_id}),
            writes=frozenset({context_id}),
            before=access,
        )

        with self.assertWarnsRegex(UnusedContextWarning, context_id):
            self.assertEqual(self.make_application(plugin).run([]), 0)

    def test_context_permissions_and_required_values_are_enforced(self) -> None:
        context_id = "tests.context.restricted"

        def verify(event, api) -> None:
            with self.assertRaises(ContextAccessError):
                api.get_context(context_id)
            with self.assertRaises(ContextAccessError):
                api.set_context(context_id, "value")

        permission_plugin = TestPlugin("tests.context.permissions", before=verify)
        self.assertEqual(self.make_application(permission_plugin).run([]), 0)

        missing_plugin = TestPlugin(
            "tests.context.required",
            reads=frozenset({context_id}),
            before=lambda event, api: api.require_context(context_id),
        )
        with contextlib.redirect_stderr(io.StringIO()):
            result = self.make_application(missing_plugin).run([])
        self.assertEqual(result, FRAMEWORK_ERROR_EXIT)

        def catch_missing(event, api) -> None:
            with self.assertRaises(MissingContextError):
                api.require_context(context_id)

        handled_plugin = TestPlugin(
            "tests.context.handled_missing",
            reads=frozenset({context_id}),
            before=catch_missing,
        )
        self.assertEqual(self.make_application(handled_plugin).run([]), 0)

    def test_api_is_closed_after_invocation(self) -> None:
        retained = []

        def retain(event, api) -> None:
            retained.append(api)

        plugin = TestPlugin(
            "tests.context.retained",
            before=retain,
        )
        result = self.make_application(plugin).run([])

        self.assertEqual(result, 0)
        with self.assertRaises(PluginPhaseError):
            retained[0].get_context("tests.context.anything")


if __name__ == "__main__":
    unittest.main()
