from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import get_type_hints

import engulf_api
from engulf_api import (
    PLUGIN_API_MAJOR,
    PLUGIN_API_VERSION,
    AfterGoalAPI,
    ApplicationMetadata,
    AttributedContribution,
    BeforeGoalAPI,
    DependencyPosition,
    DiagnosticsAPI,
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
    LockTimeoutError,
    Plugin,
    PluginDependency,
    PluginLogger,
    PluginMetadata,
    PluginOrder,
    RegistrationAPI,
    StateCatalogError,
    StateScope,
    StateStore,
    WorkspaceState,
    validate_exit_code,
    validate_global_identifier,
)

REQUIREMENT = GoalRequirement("tests.api.goal", 1)


class ExamplePlugin(Plugin):
    plugin_id = "tests.api.example"
    goal_requirement = REQUIREMENT


class ApiTestCase(unittest.TestCase):
    def test_api_version_matches_contract(self) -> None:
        self.assertEqual(PLUGIN_API_MAJOR, 1)
        self.assertEqual(PLUGIN_API_VERSION, "1.0.0")

    def test_application_metadata_is_immutable_validated_and_keyword_only(self) -> None:
        metadata = ApplicationMetadata(
            application_id="com.example.app",
            display_name="example-app",
            vendor="Example Corp",
            product="Example App",
            version="1.2.3+vendor.1",
        )

        self.assertEqual(metadata.vendor, "Example Corp")
        self.assertEqual(metadata.product, "Example App")
        self.assertEqual(metadata.version, "1.2.3+vendor.1")
        with self.assertRaises(TypeError):
            ApplicationMetadata(  # type: ignore[misc]
                "com.example.app",
                "example-app",
                "Example Corp",
                "Example App",
                "1.2.3",
            )
        for field, value in (
            ("vendor", ""),
            ("product", " surrounding "),
            ("version", "1.0\nforged"),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                ApplicationMetadata(
                    application_id="com.example.app",
                    display_name="example-app",
                    vendor="Example Corp" if field != "vendor" else value,
                    product="Example App" if field != "product" else value,
                    version="1.0" if field != "version" else value,
                )

    def test_plugin_metadata_defaults_and_priority(self) -> None:
        class EarlierPlugin(ExamplePlugin):
            priority = 25

        class OptionalElevationPlugin(ExamplePlugin):
            elevation_requirement = ElevationRequirement.OPTIONAL

        plugin = ExamplePlugin()
        self.assertEqual(plugin.priority, 50)
        self.assertEqual(EarlierPlugin().priority, 25)
        self.assertIs(plugin.elevation_requirement, ElevationRequirement.NONE)
        self.assertIs(
            OptionalElevationPlugin().elevation_requirement,
            ElevationRequirement.OPTIONAL,
        )
        self.assertEqual(
            tuple(ElevationRequirement),
            (
                ElevationRequirement.NONE,
                ElevationRequirement.OPTIONAL,
                ElevationRequirement.REQUIRED,
            ),
        )
        self.assertEqual(plugin.plugin_dependencies, ())
        self.assertEqual(plugin.context_reads, frozenset())
        self.assertEqual(plugin.context_writes, frozenset())
        self.assertEqual(plugin.goal_requirement, REQUIREMENT)
        self.assertEqual(
            plugin.metadata,
            PluginMetadata(
                plugin_id=plugin.plugin_id,
                goal_requirement=REQUIREMENT,
            ),
        )

    def test_plugin_metadata_is_validated_and_keyword_only(self) -> None:
        metadata = PluginMetadata(
            plugin_id="tests.api.metadata",
            goal_requirement=REQUIREMENT,
            context_reads=frozenset({"tests.api.context"}),
        )

        self.assertEqual(metadata.priority, 50)
        with self.assertRaises(TypeError):
            PluginMetadata(  # type: ignore[misc]
                "tests.api.metadata",
                REQUIREMENT,
            )
        with self.assertRaisesRegex(TypeError, "priority"):
            PluginMetadata(
                plugin_id="tests.api.metadata",
                goal_requirement=REQUIREMENT,
                priority=True,
            )
        with self.assertRaisesRegex(ValueError, "context identifier"):
            PluginMetadata(
                plugin_id="tests.api.metadata",
                goal_requirement=REQUIREMENT,
                context_reads=frozenset({"INVALID"}),
            )

    def test_dependency_defaults_form_middleware_order(self) -> None:
        dependency = PluginDependency("com.example.required")

        self.assertIs(dependency.preprocess, DependencyPosition.BEFORE)
        self.assertIs(dependency.postprocess, DependencyPosition.AFTER)

    def test_identifiers_must_be_lowercase_and_dot_qualified(self) -> None:
        self.assertEqual(
            validate_global_identifier("com.example.value", label="value"),
            "com.example.value",
        )
        for invalid in ("single", "Com.example.value", "com..value"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_global_identifier(invalid, label="value")

    def test_exit_codes_are_exact_bytes(self) -> None:
        self.assertEqual(validate_exit_code(0), 0)
        self.assertEqual(validate_exit_code(255), 255)
        for invalid in (True, False, -1, 256, "0", 1.0, None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_exit_code(invalid)

    def test_goal_contract_result_and_invocation_models(self) -> None:
        contract = GoalContract(REQUIREMENT, ExamplePlugin)
        self.assertEqual(contract.goal_id, "tests.api.goal")
        self.assertEqual(contract.api_major, 1)
        self.assertIs(contract.plugin_type, ExamplePlugin)

        completed = GoalResult.completed("value", exit_code=4)
        rejected = GoalResult.rejected(
            9,
            rejected_by="tests.api.example",
        )
        self.assertIs(completed.status, GoalResultStatus.COMPLETED)
        self.assertEqual(completed.value, "value")
        self.assertIs(rejected.status, GoalResultStatus.REJECTED)
        self.assertEqual(rejected.rejected_by, "tests.api.example")

        with tempfile.TemporaryDirectory() as temporary:
            invocation = Invocation(
                ("one",),
                Path(temporary).resolve(),
                {"KEY": "value"},
            )
        self.assertEqual(invocation.arguments, ("one",))
        with self.assertRaises(TypeError):
            invocation.environment["OTHER"] = "value"  # type: ignore[index]

    def test_goal_phases_are_typed_attributed_and_two_ordered(self) -> None:
        phase = GoalPhase(
            phase_id="tests.api.phase",
            order=PluginOrder.PREPROCESS,
            local_callback=lambda plugin, event, api: event,
            contribution_type=str,
        )
        contribution = AttributedContribution(
            plugin_id="tests.api.example",
            value="value",
        )
        self.assertIs(phase.order, PluginOrder.PREPROCESS)
        self.assertTrue(callable(phase.local_callback))
        self.assertEqual(contribution.value, "value")
        self.assertEqual(
            tuple(PluginOrder),
            (PluginOrder.PREPROCESS, PluginOrder.POSTPROCESS),
        )
        with self.assertRaises(TypeError):
            GoalPhase(  # type: ignore[misc]
                "tests.api.positional",
                PluginOrder.PREPROCESS,
                lambda plugin, event, api: None,
            )

    def test_lifecycle_apis_expose_only_generic_capabilities(self) -> None:
        for api_type in (
            DiagnosticsAPI,
            RegistrationAPI,
            InvocationAPI,
            BeforeGoalAPI,
            AfterGoalAPI,
            GoalSetupAPI,
            GoalAPI,
        ):
            with self.subTest(api_type=api_type.__name__), self.assertRaises(TypeError):
                api_type()

        common = {
            "application",
            "elevated",
            "lease",
            "leases",
            "get_context",
            "require_context",
            "set_context",
            "state",
            "known_workspaces",
            "logger",
        }
        self.assertTrue(common <= InvocationAPI.__abstractmethods__)
        self.assertTrue(common <= BeforeGoalAPI.__abstractmethods__)
        self.assertTrue(common <= AfterGoalAPI.__abstractmethods__)
        self.assertIn("elevated", RegistrationAPI.__abstractmethods__)
        for wrapper_method in ("remove", "remove_range", "add", "preempt"):
            self.assertFalse(hasattr(InvocationAPI, wrapper_method))
            self.assertFalse(hasattr(AfterGoalAPI, wrapper_method))

        self.assertIs(get_type_hints(Plugin.before_goal)["api"], BeforeGoalAPI)
        self.assertIs(get_type_hints(Plugin.after_goal)["api"], AfterGoalAPI)
        self.assertFalse(hasattr(PluginLogger, "setLevel"))
        self.assertFalse(hasattr(PluginLogger, "addHandler"))

    def test_goal_is_abstract(self) -> None:
        with self.assertRaises(TypeError):
            Goal()  # type: ignore[abstract]

    def test_state_contract_is_public_and_abstract(self) -> None:
        self.assertEqual(
            tuple(StateScope),
            (StateScope.WORKSPACE, StateScope.USER),
        )
        with self.assertRaises(TypeError):
            StateStore()
        with self.assertRaises(TypeError):
            WorkspaceState()
        self.assertTrue(issubclass(StateCatalogError, RuntimeError))
        self.assertTrue(issubclass(LockTimeoutError, TimeoutError))
        self.assertIn("transaction", StateStore.__abstractmethods__)

    def test_core_does_not_export_executable_wrapper_types(self) -> None:
        for name in (
            "AdditionPlacement",
            "BeforeCallEvent",
            "CallOutcome",
            "CompletionRegistry",
            "ExecutableWrapperPlugin",
        ):
            self.assertFalse(hasattr(engulf_api, name))


if __name__ == "__main__":
    unittest.main()
