from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

from engulf_api import (
    ContextAccessError,
    DependencyPosition,
    MissingContextError,
    Plugin,
    PluginDependency,
    PluginPhaseError,
    UnusedContextWarning,
)

from engulf import FRAMEWORK_ERROR_EXIT, Engulf, PluginDependencyError


class TestPlugin(Plugin):
    __test__ = False

    def __init__(
        self,
        plugin_id: str,
        *,
        priority: int = 50,
        dependencies: tuple[PluginDependency, ...] = (),
        reads: frozenset[str] = frozenset(),
        writes: frozenset[str] = frozenset(),
        before=None,
        after=None,
        calls: list[str] | None = None,
    ) -> None:
        self.plugin_id = plugin_id
        self.priority = priority
        self.plugin_dependencies = dependencies
        self.context_reads = reads
        self.context_writes = writes
        self.before_action = before
        self.after_action = after
        self.calls = calls

    def help(self) -> str:
        return self.plugin_id

    def before_call(self, event, api) -> None:
        if self.calls is not None:
            self.calls.append(f"{self.plugin_id}.before")
        if self.before_action is not None:
            self.before_action(event, api)

    def after_call(self, event, api) -> None:
        if self.calls is not None:
            self.calls.append(f"{self.plugin_id}.after")
        if self.after_action is not None:
            self.after_action(event, api)


class DependencyAndContextTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.plugin_directory = Path(self.temporary_directory.name)

    def make_engulf(self, *plugins: Plugin) -> Engulf:
        with patch(
            "engulf.wrapper.load_directory_plugins", return_value=tuple(plugins)
        ):
            return Engulf(
                "/bin/true",
                "engulf-dependency-context-tests",
                plugin_dir=self.plugin_directory,
                discover_installed=False,
            )

    def test_default_dependency_order_is_middleware_shaped(self) -> None:
        calls: list[str] = []
        required = TestPlugin("tests.order.required", priority=0, calls=calls)
        dependent = TestPlugin(
            "tests.order.dependent",
            priority=100,
            dependencies=(PluginDependency(required.plugin_id),),
            calls=calls,
        )

        app = self.make_engulf(dependent, required)
        result = app.run([])

        self.assertEqual(result, 0)
        self.assertEqual(
            [plugin.plugin_id for plugin in app.plugins],
            [required.plugin_id, dependent.plugin_id],
        )
        self.assertEqual(
            [plugin.plugin_id for plugin in app.postprocess_plugins],
            [dependent.plugin_id, required.plugin_id],
        )
        self.assertEqual(
            calls,
            [
                f"{required.plugin_id}.before",
                f"{dependent.plugin_id}.before",
                f"{dependent.plugin_id}.after",
                f"{required.plugin_id}.after",
            ],
        )

    def test_phase_constraints_are_independent(self) -> None:
        required = TestPlugin("tests.phase.required", priority=0)
        dependent = TestPlugin(
            "tests.phase.dependent",
            priority=100,
            dependencies=(
                PluginDependency(
                    required.plugin_id,
                    preprocess=None,
                    postprocess=DependencyPosition.BEFORE,
                ),
            ),
        )

        app = self.make_engulf(required, dependent)

        self.assertEqual(
            [plugin.plugin_id for plugin in app.plugins],
            [dependent.plugin_id, required.plugin_id],
        )
        self.assertEqual(
            [plugin.plugin_id for plugin in app.postprocess_plugins],
            [required.plugin_id, dependent.plugin_id],
        )

    def test_priority_applies_only_among_ready_plugins(self) -> None:
        first = TestPlugin("tests.ready.first", priority=0)
        independent = TestPlugin("tests.ready.independent", priority=50)
        blocked = TestPlugin(
            "tests.ready.blocked",
            priority=100,
            dependencies=(PluginDependency(first.plugin_id, postprocess=None),),
        )

        app = self.make_engulf(first, blocked, independent)

        self.assertEqual(
            [plugin.plugin_id for plugin in app.plugins],
            [independent.plugin_id, first.plugin_id, blocked.plugin_id],
        )

    def test_dependency_without_phase_edges_still_requires_presence(self) -> None:
        plugin = TestPlugin(
            "tests.presence.dependent",
            dependencies=(
                PluginDependency(
                    "tests.presence.missing", preprocess=None, postprocess=None
                ),
            ),
        )

        with self.assertRaisesRegex(PluginDependencyError, "requires missing plugin"):
            self.make_engulf(plugin)

    def test_rejects_duplicate_self_and_duplicate_dependency_ids(self) -> None:
        duplicate_a = TestPlugin("tests.invalid.duplicate")
        duplicate_b = TestPlugin("tests.invalid.duplicate")
        with self.assertRaisesRegex(PluginDependencyError, "duplicate plugin_id"):
            self.make_engulf(duplicate_a, duplicate_b)

        self_dependent = TestPlugin(
            "tests.invalid.self",
            dependencies=(PluginDependency("tests.invalid.self"),),
        )
        with self.assertRaisesRegex(PluginDependencyError, "depend on itself"):
            self.make_engulf(self_dependent)

        required = TestPlugin("tests.invalid.required")
        repeated = TestPlugin(
            "tests.invalid.repeated",
            dependencies=(
                PluginDependency(required.plugin_id),
                PluginDependency(required.plugin_id),
            ),
        )
        with self.assertRaisesRegex(PluginDependencyError, "more than once"):
            self.make_engulf(required, repeated)

    def test_reports_preprocess_and_postprocess_cycles(self) -> None:
        preprocess_a = TestPlugin(
            "tests.cycle.pre_a",
            dependencies=(PluginDependency("tests.cycle.pre_b", postprocess=None),),
        )
        preprocess_b = TestPlugin(
            "tests.cycle.pre_b",
            dependencies=(PluginDependency("tests.cycle.pre_a", postprocess=None),),
        )
        with self.assertRaisesRegex(
            PluginDependencyError, "preprocess plugin dependency cycle"
        ):
            self.make_engulf(preprocess_a, preprocess_b)

        postprocess_a = TestPlugin(
            "tests.cycle.post_a",
            dependencies=(
                PluginDependency(
                    "tests.cycle.post_b",
                    preprocess=None,
                    postprocess=DependencyPosition.BEFORE,
                ),
            ),
        )
        postprocess_b = TestPlugin(
            "tests.cycle.post_b",
            dependencies=(
                PluginDependency(
                    "tests.cycle.post_a",
                    preprocess=None,
                    postprocess=DependencyPosition.BEFORE,
                ),
            ),
        )
        with self.assertRaisesRegex(
            PluginDependencyError, "postprocess plugin dependency cycle"
        ):
            self.make_engulf(postprocess_a, postprocess_b)

    def test_rejects_invalid_identity_and_context_metadata(self) -> None:
        with self.assertRaisesRegex(PluginDependencyError, "dot-qualified"):
            self.make_engulf(TestPlugin("invalid"))

        invalid_context = TestPlugin(
            "tests.invalid.context", reads=frozenset({"NOT.qualified"})
        )
        with self.assertRaisesRegex(PluginDependencyError, "context identifier"):
            self.make_engulf(invalid_context)

    def test_context_persists_through_both_phases_and_resets_per_call(self) -> None:
        context_id = "tests.context.value"
        observed: list[object] = []

        def before(event, api) -> None:
            observed.append(api.get_context(context_id, "missing"))
            api.set_context(context_id, event.wrapper_args)

        def after(event, api) -> None:
            observed.append(api.require_context(context_id))

        plugin = TestPlugin(
            "tests.context.lifecycle",
            reads=frozenset({context_id}),
            writes=frozenset({context_id}),
            before=before,
            after=after,
        )
        app = self.make_engulf(plugin)

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
            result = self.make_engulf(reader, second, first).run([])

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
            result = self.make_engulf(plugin).run([])

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
            self.assertEqual(self.make_engulf(plugin).run([]), 0)

    def test_context_permissions_and_required_values_are_enforced(self) -> None:
        context_id = "tests.context.restricted"

        def verify(event, api) -> None:
            with self.assertRaises(ContextAccessError):
                api.get_context(context_id)
            with self.assertRaises(ContextAccessError):
                api.set_context(context_id, "value")

        permission_plugin = TestPlugin("tests.context.permissions", before=verify)
        self.assertEqual(self.make_engulf(permission_plugin).run([]), 0)

        missing_plugin = TestPlugin(
            "tests.context.required",
            reads=frozenset({context_id}),
            before=lambda event, api: api.require_context(context_id),
        )
        with contextlib.redirect_stderr(io.StringIO()):
            result = self.make_engulf(missing_plugin).run([])
        self.assertEqual(result, FRAMEWORK_ERROR_EXIT)

        def catch_missing(event, api) -> None:
            with self.assertRaises(MissingContextError):
                api.require_context(context_id)

        handled_plugin = TestPlugin(
            "tests.context.handled_missing",
            reads=frozenset({context_id}),
            before=catch_missing,
        )
        self.assertEqual(self.make_engulf(handled_plugin).run([]), 0)

    def test_api_is_closed_after_call_and_edits_are_preprocess_only(self) -> None:
        retained = []

        def retain(event, api) -> None:
            retained.append(api)

        plugin = TestPlugin(
            "tests.context.retained",
            before=retain,
            after=lambda event, api: api.add("--too-late"),
        )
        with contextlib.redirect_stderr(io.StringIO()):
            result = self.make_engulf(plugin).run([])

        self.assertEqual(result, FRAMEWORK_ERROR_EXIT)
        with self.assertRaises(PluginPhaseError):
            retained[0].get_context("tests.context.anything")


if __name__ == "__main__":
    unittest.main()
