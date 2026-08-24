from __future__ import annotations

import contextlib
import io
import tempfile
import threading
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from engulf_api import (
    ApplicationMetadata,
    ElevationRequirement,
    Goal,
    GoalAPI,
    GoalContract,
    GoalPhase,
    GoalRequirement,
    GoalResult,
    GoalResultStatus,
    GoalSetupAPI,
    Invocation,
    InvocationAPI,
    Plugin,
    PluginOrder,
    PluginPhaseError,
    RegistrationAPI,
)

from engulf import (
    FRAMEWORK_ERROR_EXIT,
    ActivePlugin,
    Application,
    PluginElevationError,
    PluginRequirementError,
    PluginSourceKind,
)

REQUIREMENT = GoalRequirement("tests.application.goal", 1)


class ApplicationPlugin(Plugin):
    goal_requirement = REQUIREMENT

    def __init__(
        self,
        plugin_id: str,
        *,
        priority: int = 50,
        contribution: str | None = None,
        elevation_requirement: ElevationRequirement = ElevationRequirement.NONE,
        registration=None,
        before=None,
        after=None,
    ) -> None:
        self.plugin_id = plugin_id
        self.priority = priority
        self.contribution = contribution
        self.elevation_requirement = elevation_requirement
        self.registration_action = registration
        self.before_action = before
        self.after_action = after

    def before_goal(self, invocation, api):
        if self.before_action is None:
            return None
        return self.before_action(invocation, api)

    def after_goal(self, invocation, result, api):
        if self.after_action is None:
            return result
        return self.after_action(invocation, result, api)


def _contribute(
    plugin: ApplicationPlugin,
    event: tuple[str, ...],
    api: InvocationAPI,
) -> str | None:
    del event, api
    return plugin.contribution


def _register(
    plugin: ApplicationPlugin,
    event: None,
    api: RegistrationAPI,
) -> None:
    del event
    if plugin.registration_action is not None:
        plugin.registration_action(api)


CONTRIBUTE = GoalPhase(
    phase_id="tests.application.contribute",
    order=PluginOrder.PREPROCESS,
    local_callback=_contribute,
    contribution_type=str,
)
REGISTER = GoalPhase(
    phase_id="tests.application.register",
    order=PluginOrder.PREPROCESS,
    local_callback=_register,
)


class RecordingGoal(Goal[tuple[tuple[str, str], ...]]):
    _contract = GoalContract(REQUIREMENT, ApplicationPlugin)

    def __init__(self) -> None:
        self.setup_count = 0
        self.achieve_count = 0

    @property
    def contract(self) -> GoalContract:
        return self._contract

    def setup(self, api: GoalSetupAPI) -> None:
        self.setup_count += 1
        self.setup_elevated = api.elevated
        self.setup_application = api.application
        self.setup_identity = (api.application_id, api.display_name, api.plugin_ids)
        api.dispatch(REGISTER, None)

    def achieve(self, invocation: Invocation, api: GoalAPI):
        self.achieve_count += 1
        self.achieve_elevated = api.elevated
        self.achieve_application = api.application
        contributions = api.dispatch(CONTRIBUTE, invocation.arguments)
        value = tuple(
            (contribution.plugin_id, contribution.value)
            for contribution in contributions
        )
        return GoalResult.completed(value)


class NormalizingGoal(RecordingGoal):
    def normalize_invocation(self, invocation: Invocation) -> Invocation:
        return Invocation(
            ("normalized", *invocation.arguments),
            invocation.cwd,
            {**invocation.environment, "NORMALIZED": "1"},
        )

    def achieve(self, invocation: Invocation, api: GoalAPI):
        self.achieve_invocation = invocation
        return super().achieve(invocation, api)


class ApplicationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.plugin_directory = Path(self.temporary_directory.name)

    def make_application(
        self,
        goal: RecordingGoal,
        *plugins: ApplicationPlugin,
    ) -> Application:
        with patch(
            "engulf.application.load_directory_plugins",
            return_value=plugins,
        ):
            return Application(
                "tests-application",
                goal,
                display_name="test-application",
                vendor="Engulf Tests",
                product="Application Tests",
                short_product_name="Application",
                version="0.test",
                plugin_dir=self.plugin_directory,
                discover_installed=False,
            )

    def test_setup_runs_once_and_goal_receives_attributed_contributions(self) -> None:
        goal = RecordingGoal()
        first = ApplicationPlugin(
            "tests.application.first",
            priority=100,
            contribution="one",
        )
        second = ApplicationPlugin(
            "tests.application.second",
            contribution="two",
        )
        application = self.make_application(goal, second, first)

        result = application.invoke(("payload",))

        self.assertIs(result.status, GoalResultStatus.COMPLETED)
        self.assertEqual(
            result.value,
            (
                (first.plugin_id, "one"),
                (second.plugin_id, "two"),
            ),
        )
        self.assertEqual(goal.setup_count, 1)
        self.assertEqual(goal.achieve_count, 1)
        self.assertTrue(
            all(isinstance(item, ActivePlugin) for item in application.plugins)
        )
        self.assertIsNot(application.plugins[0], first)
        self.assertEqual(application.plugins, application.active_plugins)
        self.assertIs(
            application.plugins[0].source.kind,
            PluginSourceKind.DIRECTORY,
        )
        self.assertEqual(
            application.plugins[0].source.directory,
            self.plugin_directory.resolve(),
        )
        self.assertIs(application.elevated, goal.setup_elevated)
        expected_metadata = ApplicationMetadata(
            application_id="tests-application",
            display_name="test-application",
            vendor="Engulf Tests",
            product="Application Tests",
            short_product_name="Application",
            version="0.test",
        )
        self.assertEqual(application.application_metadata, expected_metadata)
        self.assertEqual(application.short_product_name, "Application")
        self.assertEqual(goal.setup_application, expected_metadata)
        self.assertEqual(goal.achieve_application, expected_metadata)
        self.assertEqual(
            goal.setup_identity,
            (
                "tests-application",
                "test-application",
                (first.plugin_id, second.plugin_id),
            ),
        )

    def test_goal_normalizes_invocation_before_outer_callbacks(self) -> None:
        observed: list[Invocation] = []
        goal = NormalizingGoal()
        plugin = ApplicationPlugin(
            "tests.application.normalized",
            before=lambda invocation, api: observed.append(invocation),
        )
        application = self.make_application(goal, plugin)

        result = application.invoke(("original",))

        self.assertIs(result.status, GoalResultStatus.COMPLETED)
        self.assertEqual(observed, [goal.achieve_invocation])
        self.assertEqual(observed[0].arguments, ("normalized", "original"))
        self.assertEqual(observed[0].environment["NORMALIZED"], "1")

    def test_invalid_goal_normalization_is_a_framework_failure(self) -> None:
        class InvalidNormalizingGoal(RecordingGoal):
            def normalize_invocation(self, invocation: Invocation) -> Invocation:
                del invocation
                return object()  # type: ignore[return-value]

        goal = InvalidNormalizingGoal()
        application = self.make_application(goal)

        with contextlib.redirect_stderr(io.StringIO()):
            result = application.invoke(())

        self.assertIs(result.status, GoalResultStatus.FRAMEWORK_FAILED)
        self.assertEqual(result.exit_code, FRAMEWORK_ERROR_EXIT)
        self.assertEqual(goal.achieve_count, 0)

    def test_plugin_elevation_requirements_are_enforced_and_available(self) -> None:
        blocked_goal = RecordingGoal()
        blocked_calls: list[bool] = []
        required = ApplicationPlugin(
            "tests.application.elevation_required",
            elevation_requirement=ElevationRequirement.REQUIRED,
            registration=lambda api: blocked_calls.append(api.elevated),
        )
        with (
            patch("engulf.application.is_process_elevated", return_value=False),
            self.assertRaisesRegex(
                PluginElevationError,
                "elevation is required.*tests.application.elevation_required",
            ),
        ):
            self.make_application(blocked_goal, required)
        self.assertEqual(blocked_goal.setup_count, 0)
        self.assertEqual(blocked_calls, [])

        observed: list[tuple[str, bool]] = []
        observed_applications: list[ApplicationMetadata] = []
        retained_apis: list[RegistrationAPI | InvocationAPI] = []

        def record(
            phase: str,
        ) -> Callable[[RegistrationAPI | InvocationAPI], None]:
            def inspect(api: RegistrationAPI | InvocationAPI) -> None:
                observed.append((phase, api.elevated))
                observed_applications.append(api.application)
                retained_apis.append(api)

            return inspect

        optional = ApplicationPlugin(
            "tests.application.elevation_optional",
            elevation_requirement=ElevationRequirement.OPTIONAL,
            registration=record("registration"),
            before=lambda invocation, api: record("invocation")(api),
        )
        optional_goal = RecordingGoal()
        with patch("engulf.application.is_process_elevated", return_value=False):
            application = self.make_application(optional_goal, optional)
        self.assertFalse(application.elevated)
        self.assertFalse(optional_goal.setup_elevated)
        self.assertEqual(application.run(()), 0)
        self.assertFalse(optional_goal.achieve_elevated)
        self.assertEqual(
            observed,
            [("registration", False), ("invocation", False)],
        )
        self.assertEqual(
            observed_applications,
            [optional_goal.setup_application, optional_goal.setup_application],
        )
        for api in retained_apis:
            with self.assertRaises(PluginPhaseError):
                _ = api.elevated
            with self.assertRaises(PluginPhaseError):
                _ = api.application

        elevated_goal = RecordingGoal()
        elevated_calls: list[bool] = []
        elevated_required = ApplicationPlugin(
            "tests.application.elevated_required",
            elevation_requirement=ElevationRequirement.REQUIRED,
            registration=lambda api: elevated_calls.append(api.elevated),
        )
        with patch("engulf.application.is_process_elevated", return_value=True):
            elevated_application = self.make_application(
                elevated_goal,
                elevated_required,
            )
        self.assertTrue(elevated_application.elevated)
        self.assertEqual(elevated_calls, [True])

    def test_first_before_result_short_circuits_and_only_entered_plugin_unwinds(
        self,
    ) -> None:
        calls: list[str] = []
        goal = RecordingGoal()

        def reject(invocation, api):
            del invocation, api
            calls.append("first.before")
            return GoalResult.rejected(12)

        def first_after(invocation, result, api):
            del invocation, api
            calls.append("first.after")
            return result

        first = ApplicationPlugin(
            "tests.application.first",
            priority=100,
            before=reject,
            after=first_after,
        )
        second = ApplicationPlugin(
            "tests.application.second",
            before=lambda invocation, api: calls.append("second.before"),
            after=lambda invocation, result, api: calls.append("second.after"),
        )
        application = self.make_application(goal, second, first)

        result = application.invoke(())

        self.assertIs(result.status, GoalResultStatus.REJECTED)
        self.assertEqual(result.exit_code, 12)
        self.assertEqual(result.rejected_by, first.plugin_id)
        self.assertEqual(calls, ["first.before", "first.after"])
        self.assertEqual(goal.achieve_count, 0)

    def test_after_results_compose_in_postprocess_order(self) -> None:
        goal = RecordingGoal()

        def append(label: str):
            def transform(invocation, result, api):
                del invocation, api
                value = tuple(result.value or ()) + ((label, label),)
                return GoalResult.completed(value, exit_code=result.exit_code)

            return transform

        dependency = ApplicationPlugin(
            "tests.application.dependency",
            contribution="dependency",
            after=append("dependency-after"),
        )
        from engulf_api import PluginDependency

        dependent = ApplicationPlugin(
            "tests.application.dependent",
            contribution="dependent",
            after=append("dependent-after"),
        )
        dependent.plugin_dependencies = (PluginDependency(dependency.plugin_id),)
        application = self.make_application(goal, dependent, dependency)

        result = application.invoke(())

        self.assertEqual(
            result.value,
            (
                (dependency.plugin_id, "dependency"),
                (dependent.plugin_id, "dependent"),
                ("dependent-after", "dependent-after"),
                ("dependency-after", "dependency-after"),
            ),
        )

    def test_callback_failure_becomes_framework_result(self) -> None:
        goal = RecordingGoal()
        plugin = ApplicationPlugin(
            "tests.application.failure",
            before=lambda invocation, api: (_ for _ in ()).throw(
                RuntimeError("before failed")
            ),
        )
        application = self.make_application(goal, plugin)

        with contextlib.redirect_stderr(io.StringIO()):
            result = application.invoke(())

        self.assertIs(result.status, GoalResultStatus.FRAMEWORK_FAILED)
        self.assertEqual(result.exit_code, FRAMEWORK_ERROR_EXIT)
        self.assertEqual(goal.achieve_count, 0)

    def test_after_failure_stops_later_postprocessors(self) -> None:
        calls: list[str] = []
        goal = RecordingGoal()

        def fail(invocation, result, api):
            del invocation, result, api
            calls.append("failing.after")
            raise RuntimeError("after failed")

        def later(invocation, result, api):
            del invocation, api
            calls.append("later.after")
            return result

        failing = ApplicationPlugin(
            "tests.application.failing",
            priority=100,
            after=fail,
        )
        later_plugin = ApplicationPlugin(
            "tests.application.later",
            after=later,
        )
        application = self.make_application(goal, later_plugin, failing)

        with contextlib.redirect_stderr(io.StringIO()):
            result = application.invoke(())

        self.assertIs(result.status, GoalResultStatus.FRAMEWORK_FAILED)
        self.assertEqual(result.exit_code, FRAMEWORK_ERROR_EXIT)
        self.assertEqual(calls, ["failing.after"])

    def test_plugin_descriptors_are_snapshotted_and_application_is_closeable(
        self,
    ) -> None:
        goal = RecordingGoal()
        plugin = ApplicationPlugin(
            "tests.application.descriptor",
            priority=75,
        )
        application = self.make_application(goal, plugin)
        descriptor = application.active_plugins[0]

        plugin.priority = 1

        self.assertEqual(descriptor.priority, 75)
        self.assertFalse(application.closed)
        self.assertIs(application.__enter__(), application)
        with patch(
            "engulf._plugin_execution._InProcessPluginEndpoint.close",
            autospec=True,
        ) as close:
            application.__exit__(None, None, None)
            application.close()
            close.assert_called_once()
        self.assertTrue(application.closed)
        with self.assertRaisesRegex(RuntimeError, "application is closed"):
            application.invoke(())

    def test_setup_failure_closes_all_created_execution_endpoints(self) -> None:
        plugin = ApplicationPlugin(
            "tests.application.setup_failure",
            registration=lambda api: (_ for _ in ()).throw(
                RuntimeError("setup failed")
            ),
        )

        with (
            patch(
                "engulf._plugin_execution._InProcessPluginEndpoint.close",
                autospec=True,
            ) as close,
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaisesRegex(RuntimeError, "setup failed"),
        ):
            self.make_application(RecordingGoal(), plugin)

        close.assert_called_once()

    def test_resolution_failure_closes_all_discovered_execution_endpoints(
        self,
    ) -> None:
        from engulf_api import PluginDependency

        first = ApplicationPlugin("tests.application.resolution_first")
        second = ApplicationPlugin("tests.application.resolution_second")
        second.plugin_dependencies = (
            PluginDependency("tests.application.resolution_missing"),
        )

        with (
            patch(
                "engulf._plugin_execution._InProcessPluginEndpoint.close",
                autospec=True,
            ) as close,
            self.assertRaisesRegex(RuntimeError, "requires missing plugin"),
        ):
            self.make_application(RecordingGoal(), first, second)

        self.assertEqual(close.call_count, 2)

    def test_missing_required_plugin_closes_endpoints_before_setup(self) -> None:
        goal = RecordingGoal()
        available = ApplicationPlugin("tests.application.available")

        with (
            patch(
                "engulf._plugin_execution._InProcessPluginEndpoint.close",
                autospec=True,
            ) as close,
            patch(
                "engulf.application.load_directory_plugins",
                return_value=(available,),
            ),
            self.assertRaisesRegex(
                PluginRequirementError,
                "tests.application.required",
            ),
        ):
            Application(
                "tests-application",
                goal,
                display_name="test-application",
                vendor="Engulf Tests",
                product="Application Tests",
                short_product_name="Application",
                version="0.test",
                required_plugin_ids=("tests.application.required",),
                plugin_dir=self.plugin_directory,
                discover_installed=False,
            )

        close.assert_called_once()
        self.assertEqual(goal.setup_count, 0)

    def test_overlapping_invocation_and_close_are_rejected(self) -> None:
        started = threading.Event()
        release = threading.Event()
        results: list[int] = []

        def wait_for_release(invocation, api) -> None:
            del invocation, api
            started.set()
            if not release.wait(5):
                raise RuntimeError("test invocation was not released")

        application = self.make_application(
            RecordingGoal(),
            ApplicationPlugin(
                "tests.application.concurrency",
                before=wait_for_release,
            ),
        )
        thread = threading.Thread(target=lambda: results.append(application.run(())))
        thread.start()
        try:
            self.assertTrue(started.wait(2))
            with self.assertRaisesRegex(RuntimeError, "already active"):
                application.invoke(())
            with self.assertRaisesRegex(RuntimeError, "during an invocation"):
                application.close()
        finally:
            release.set()
            thread.join(5)

        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [0])
        application.close()


if __name__ == "__main__":
    unittest.main()
