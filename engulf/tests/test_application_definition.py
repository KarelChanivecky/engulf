from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from engulf_api import (
    Goal,
    GoalAPI,
    GoalContract,
    GoalRequirement,
    GoalResult,
    GoalSetupAPI,
    Invocation,
    Plugin,
    StateScope,
)

from engulf import ApplicationDefinition, PluginPolicy

REQUIREMENT = GoalRequirement("tests.definition.goal", 1)


class DefinitionPlugin(Plugin):
    goal_requirement = REQUIREMENT


class DefinitionGoal(Goal[str]):
    _contract = GoalContract(REQUIREMENT, DefinitionPlugin)

    def __init__(self) -> None:
        self.setup_display_name: str | None = None
        self.setup_plugin_ids: tuple[str, ...] = ()
        self.setup_postprocess_plugin_ids: tuple[str, ...] = ()
        self.setup_dependency_map: dict[str, tuple[str, ...]] = {}

    @property
    def contract(self) -> GoalContract:
        return self._contract

    def setup(self, api: GoalSetupAPI) -> None:
        self.setup_display_name = api.display_name
        self.setup_application = api.application
        self.setup_plugin_ids = api.plugin_ids
        self.setup_postprocess_plugin_ids = api.postprocess_plugin_ids
        self.setup_dependency_map = dict(api.dependency_map)

    def achieve(
        self,
        invocation: Invocation,
        api: GoalAPI,
    ) -> GoalResult[str]:
        del invocation, api
        assert self.setup_display_name is not None
        return GoalResult.completed(self.setup_display_name)


class StateDefinitionGoal(DefinitionGoal):
    def achieve(
        self,
        invocation: Invocation,
        api: GoalAPI,
    ) -> GoalResult[str]:
        state = api.state(StateScope.USER)
        if invocation.arguments and invocation.arguments[0] == "write":
            state.write_text("value.txt", invocation.arguments[1])
        value = state.read_text("value.txt") if state.exists("value.txt") else "missing"
        return GoalResult.completed(value)


class ApplicationDefinitionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        elevation = patch("engulf.application.is_process_elevated", return_value=False)
        elevation.start()
        self.addCleanup(elevation.stop)

    def test_definition_is_lazy_and_creates_fresh_goals(self) -> None:
        goals: list[DefinitionGoal] = []

        def create_goal() -> DefinitionGoal:
            goal = DefinitionGoal()
            goals.append(goal)
            return goal

        definition = ApplicationDefinition(
            application_id="Tests.Definition_App",
            display_name="definition-app",
            goal_factory=create_goal,
            vendor="Engulf Tests",
            product="Definition Tests",
            short_product_name="Definition",
            version="0.test",
        )

        self.assertEqual(goals, [])
        self.assertEqual(definition.application_id, "tests-definition-app")
        first = definition.create(discover_installed=False)
        second = definition.create(discover_installed=False)
        self.addCleanup(first.close)
        self.addCleanup(second.close)

        self.assertEqual(len(goals), 2)
        self.assertIsNot(first.goal, second.goal)
        self.assertEqual(first.application_metadata, goals[0].setup_application)
        self.assertEqual(goals[0].setup_plugin_ids, ())
        self.assertEqual(goals[0].setup_postprocess_plugin_ids, ())
        self.assertEqual(goals[0].setup_dependency_map, {})
        self.assertEqual(first.invoke(()).value, "definition-app")
        self.assertEqual(second.invoke(()).value, "definition-app")

    def test_edition_is_additive_and_retains_application_identity(self) -> None:
        base = ApplicationDefinition(
            application_id="tests.definition.base",
            display_name="base-app",
            goal_factory=DefinitionGoal,
            vendor="Base Vendor",
            product="Base Product",
            short_product_name="Base",
            version="1.0",
            plugin_policy=PluginPolicy.declared(
                include={"tests.definition.base-optional"}
            ),
            required_plugin_ids=frozenset({"tests.definition.base-required"}),
            plugin_declaration_application_ids=("tests.definition.ancestor",),
        )

        edition = base.edition(
            display_name="vendor-app",
            vendor="Vendor Corp",
            product="Vendor Product",
            short_product_name="Vendor",
            version="2.0-vendor",
            include_plugins={"tests.definition.vendor-optional"},
            require_plugins={"tests.definition.vendor-required"},
        )

        self.assertEqual(edition.application_id, base.application_id)
        self.assertEqual(edition.display_name, "vendor-app")
        self.assertEqual(edition.vendor, "Vendor Corp")
        self.assertEqual(edition.product, "Vendor Product")
        self.assertEqual(edition.short_product_name, "Vendor")
        self.assertEqual(edition.version, "2.0-vendor")
        self.assertEqual(edition.application_metadata.vendor, edition.vendor)
        self.assertIs(edition.goal_factory, base.goal_factory)
        self.assertEqual(
            edition.plugin_declaration_application_ids,
            base.plugin_declaration_application_ids,
        )
        self.assertEqual(
            edition.required_plugin_ids,
            frozenset(
                {
                    "tests.definition.base-required",
                    "tests.definition.vendor-required",
                }
            ),
        )
        self.assertEqual(
            edition.plugin_policy.plugin_ids,
            frozenset(
                {
                    "tests.definition.base-optional",
                    "tests.definition.base-required",
                    "tests.definition.vendor-optional",
                    "tests.definition.vendor-required",
                }
            ),
        )

    def test_edition_metadata_reaches_goal_callbacks(self) -> None:
        base = ApplicationDefinition(
            application_id="tests.definition.base",
            display_name="base-app",
            goal_factory=DefinitionGoal,
            vendor="Base Vendor",
            product="Base Product",
            short_product_name="Base",
            version="1.0",
        )
        edition = base.edition(
            display_name="vendor-app",
            vendor="Vendor Corp",
            product="Vendor Product",
            short_product_name="Vendor",
            version="2.0",
        )

        with edition.create(discover_installed=False) as application:
            goal = application.goal
            self.assertEqual(goal.setup_application, edition.application_metadata)
            self.assertEqual(
                application.application_metadata, edition.application_metadata
            )
            self.assertEqual(application.vendor, "Vendor Corp")
            self.assertEqual(application.product, "Vendor Product")
            self.assertEqual(application.short_product_name, "Vendor")
            self.assertEqual(application.version, "2.0")
            self.assertEqual(application.invoke(()).value, "vendor-app")

    def test_edition_can_unblock_plugins_without_changing_policy_mode(self) -> None:
        base = ApplicationDefinition(
            application_id="tests.definition.base",
            display_name="base-app",
            goal_factory=DefinitionGoal,
            vendor="Base Vendor",
            product="Base Product",
            short_product_name="Base",
            version="1.0",
            plugin_policy=PluginPolicy.allow_all_except(
                {"tests.definition.blocked", "tests.definition.still-blocked"}
            ),
        )

        edition = base.edition(
            display_name="vendor-app",
            include_plugins={"tests.definition.blocked"},
        )

        self.assertEqual(
            edition.plugin_policy.plugin_ids,
            frozenset({"tests.definition.still-blocked"}),
        )
        self.assertEqual(edition.vendor, base.vendor)
        self.assertEqual(edition.product, base.product)
        self.assertEqual(edition.short_product_name, base.short_product_name)
        self.assertEqual(edition.version, base.version)

    def test_fork_isolates_identity_and_inherits_declarations_only_by_opt_in(
        self,
    ) -> None:
        base = ApplicationDefinition(
            application_id="tests.definition.base",
            display_name="base-app",
            goal_factory=DefinitionGoal,
            vendor="Base Vendor",
            product="Base Product",
            short_product_name="Base",
            version="1.0",
            plugin_declaration_application_ids=("tests.definition.ancestor",),
        )

        isolated = base.fork(
            application_id="tests.definition.fork",
            display_name="fork-app",
        )
        inherited = base.fork(
            application_id="tests.definition.inherited-fork",
            display_name="inherited-fork",
            vendor="Fork Vendor",
            short_product_name="Fork",
            inherit_declarations=True,
        )

        self.assertEqual(
            isolated.plugin_declaration_application_ids,
            ("tests-definition-fork",),
        )
        self.assertEqual(
            inherited.plugin_declaration_application_ids,
            (
                "tests-definition-inherited-fork",
                "tests-definition-base",
                "tests-definition-ancestor",
            ),
        )
        self.assertNotEqual(isolated.application_id, base.application_id)
        self.assertNotEqual(inherited.application_id, base.application_id)
        self.assertEqual(isolated.vendor, base.vendor)
        self.assertEqual(isolated.short_product_name, base.short_product_name)
        self.assertEqual(inherited.vendor, "Fork Vendor")
        self.assertEqual(inherited.short_product_name, "Fork")

    def test_editions_share_state_while_forks_are_isolated(self) -> None:
        with TemporaryDirectory() as state_home:
            base = ApplicationDefinition(
                application_id="tests.definition.base",
                display_name="base-app",
                goal_factory=StateDefinitionGoal,
                vendor="Base Vendor",
                product="Base Product",
                short_product_name="Base",
                version="1.0",
                state_home_resolver=lambda context: state_home,
            )
            edition = base.edition(display_name="vendor-app")
            fork = base.fork(
                application_id="tests.definition.fork",
                display_name="fork-app",
            )

            with base.create(discover_installed=False) as base_application:
                self.assertEqual(
                    base_application.invoke(("write", "shared")).value,
                    "shared",
                )
            with edition.create(discover_installed=False) as edition_application:
                self.assertEqual(edition_application.invoke(("read",)).value, "shared")
            with fork.create(discover_installed=False) as fork_application:
                self.assertEqual(fork_application.invoke(("read",)).value, "missing")

    def test_definition_rejects_invalid_factories_and_fork_flags(self) -> None:
        with self.assertRaisesRegex(TypeError, "goal_factory must be callable"):
            ApplicationDefinition(
                application_id="tests.definition.invalid",
                display_name="invalid-app",
                goal_factory=object(),  # type: ignore[arg-type]
                vendor="Engulf Tests",
                product="Invalid Definition",
                short_product_name="Invalid",
                version="0.test",
            )

        definition = ApplicationDefinition(
            application_id="tests.definition.base",
            display_name="base-app",
            goal_factory=DefinitionGoal,
            vendor="Base Vendor",
            product="Base Product",
            short_product_name="Base",
            version="1.0",
        )
        with self.assertRaisesRegex(TypeError, "must be a boolean"):
            definition.fork(
                application_id="tests.definition.fork",
                display_name="fork-app",
                inherit_declarations=1,  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
