from __future__ import annotations

import inspect
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
    DiagnosticContribution,
    DiagnosticExtension,
    DiagnosticRequest,
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
    PluginCallbackError,
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


class ExampleGoal(Goal[str]):
    @property
    def contract(self) -> GoalContract:
        return GoalContract(REQUIREMENT, ExamplePlugin)

    def achieve(self, invocation: Invocation, api: GoalAPI) -> GoalResult[str]:
        del invocation, api
        return GoalResult.completed("complete")


class ApiTestCase(unittest.TestCase):
    def test_api_version_matches_contract(self) -> None:
        self.assertEqual(PLUGIN_API_MAJOR, 1)
        self.assertEqual(PLUGIN_API_VERSION, "1.1.0")

    def test_application_metadata_is_immutable_validated_and_keyword_only(self) -> None:
        metadata = ApplicationMetadata(
            application_id="com.example.app",
            display_name="example-app",
            vendor="Example Corp",
            product="Example App",
            short_product_name="Example",
            version="1.2.3+vendor.1",
        )

        self.assertEqual(metadata.vendor, "Example Corp")
        self.assertEqual(metadata.product, "Example App")
        self.assertEqual(metadata.short_product_name, "Example")
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
            ("short_product_name", ""),
            ("version", "1.0\nforged"),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                ApplicationMetadata(
                    application_id="com.example.app",
                    display_name="example-app",
                    vendor="Example Corp" if field != "vendor" else value,
                    product="Example App" if field != "product" else value,
                    short_product_name=(
                        "Example" if field != "short_product_name" else value
                    ),
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
        self.assertFalse(hasattr(plugin, "plugin_dependencies"))
        self.assertEqual(plugin.metadata.plugin_dependencies, ())
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

    def test_dependencies_are_runtime_derived_and_must_order_the_target(self) -> None:
        middleware = PluginDependency(
            "com.example.required",
            DependencyPosition.BEFORE,
            DependencyPosition.AFTER,
        )

        self.assertIs(middleware.preprocess, DependencyPosition.BEFORE)
        self.assertIs(middleware.postprocess, DependencyPosition.AFTER)
        self.assertIsNone(
            PluginDependency(
                "com.example.required",
                None,
                DependencyPosition.BEFORE,
            ).preprocess
        )
        with self.assertRaisesRegex(ValueError, "must order it in the preprocess"):
            PluginDependency("com.example.required", None, None)
        with self.assertRaises(TypeError):
            PluginDependency("com.example.required", "before", None)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            PluginDependency("com.example.required")  # type: ignore[call-arg]
        self.assertEqual(
            PluginMetadata(
                plugin_id="tests.api.metadata",
                goal_requirement=REQUIREMENT,
                plugin_dependencies=(middleware,),
            ).plugin_dependencies,
            (middleware,),
        )

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
        self.assertIs(ExampleGoal().normalize_invocation(invocation), invocation)
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

    def test_phase_failure_isolation_is_opt_in_and_validated(self) -> None:
        def phase(**overrides: object) -> GoalPhase[object, object, object, object]:
            return GoalPhase(
                phase_id="tests.api.cleanup",
                order=PluginOrder.POSTPROCESS,
                local_callback=lambda plugin, event, api: None,
                **overrides,  # type: ignore[arg-type]
            )

        self.assertFalse(phase().isolate_failures)
        self.assertTrue(phase(isolate_failures=True).isolate_failures)
        with self.assertRaises(TypeError):
            phase(isolate_failures=1)

    def test_callback_failures_are_attributed_to_a_plugin_and_a_phase(self) -> None:
        cause = RuntimeError("prepare failed")
        error = PluginCallbackError(
            "tests.api.failing",
            "tests.api.phase",
            cause,
            completed_plugin_ids=("tests.api.first", "tests.api.second"),
        )

        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(error.plugin_id, "tests.api.failing")
        self.assertEqual(error.phase, "tests.api.phase")
        self.assertIs(error.error, cause)
        self.assertEqual(
            error.completed_plugin_ids,
            ("tests.api.first", "tests.api.second"),
        )
        self.assertEqual(
            str(error),
            "plugin tests.api.failing failed in tests.api.phase: prepare failed",
        )
        self.assertEqual(
            PluginCallbackError(
                "tests.api.failing",
                "tests.api.phase",
                cause,
            ).completed_plugin_ids,
            (),
        )

    def test_goal_dispatch_accepts_an_explicit_plugin_selection(self) -> None:
        signature = inspect.signature(GoalAPI.dispatch)
        parameter = signature.parameters["plugin_ids"]

        self.assertIs(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIsNone(parameter.default)
        self.assertNotIn(
            "plugin_ids", inspect.signature(GoalSetupAPI.dispatch).parameters
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

    def test_diagnostic_contracts_and_result_are_validated(self) -> None:
        request = DiagnosticRequest(
            arguments=("--inspect",),
            application=ApplicationMetadata(
                application_id="tests.api.app",
                display_name="api-app",
                vendor="Tests",
                product="API",
                short_product_name="API",
                version="1",
            ),
            goal=REQUIREMENT,
        )
        extension = DiagnosticExtension(
            diagnostic_id="tests.api.diagnostic",
            triggers=("--inspect",),
            distribution="tests-api-diagnostic",
            version="1",
            target="tests_diagnostic:plugin",
        )
        contribution = DiagnosticContribution(stdout="ok\n", exit_code=9)
        result = GoalResult.diagnostic(
            (extension.diagnostic_id,), exit_code=contribution.exit_code
        )

        self.assertEqual(request.arguments, ("--inspect",))
        self.assertIsNone(extension.available)
        self.assertFalse(hasattr(request, "environment"))
        self.assertFalse(hasattr(request, "cwd"))
        self.assertIs(result.status, GoalResultStatus.DIAGNOSTIC)
        self.assertEqual(result.contributing_diagnostic_ids, (extension.diagnostic_id,))
        with self.assertRaises(ValueError):
            DiagnosticContribution(exit_code=256)
        with self.assertRaises(ValueError):
            DiagnosticExtension(
                diagnostic_id="tests.api.bad",
                triggers=("not-an-option",),
                distribution="tests",
                version="1",
                target="module:value",
                available=True,
            )
        with self.assertRaises(ValueError):
            DiagnosticExtension(
                diagnostic_id="tests.api.bad-availability",
                triggers=("--inspect",),
                distribution="tests",
                version="1",
                target="module:value",
                unavailable_reason="not available",
            )

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
