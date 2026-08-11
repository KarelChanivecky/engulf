from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from importlib.metadata import EntryPoint
from pathlib import Path
from unittest.mock import patch

from engulf.plugin_loader import load_directory_plugins, normalize_application_id
from engulf_api import (
    Goal,
    GoalAPI,
    GoalContract,
    GoalRequirement,
    GoalResult,
    Invocation,
    Plugin,
    PluginDependency,
)

import engulf
from engulf import (
    Application,
    PluginDependencyError,
    PluginLoadError,
    PluginPolicy,
    PluginPolicyMode,
    PluginRequirementError,
    PluginSourceKind,
    application_plugin_entry_point_group,
    goal_plugin_entry_point_group,
)

REQUIREMENT = GoalRequirement("tests.loader.goal", 1)


class LoaderGoal(Goal[tuple[str, ...]]):
    _contract = GoalContract(REQUIREMENT, Plugin)

    @property
    def contract(self) -> GoalContract:
        return self._contract

    def achieve(
        self,
        invocation: Invocation,
        api: GoalAPI,
    ) -> GoalResult[tuple[str, ...]]:
        del api
        return GoalResult.completed(invocation.arguments)


class LoaderPlugin(Plugin):
    goal_requirement = REQUIREMENT

    def __init__(
        self,
        plugin_id: str,
        *,
        priority: int = 50,
        dependencies: tuple[PluginDependency, ...] = (),
    ) -> None:
        self.plugin_id = plugin_id
        self.priority = priority
        self.plugin_dependencies = dependencies


class PluginLoaderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)
        self.plugin_directory = self.directory / "plugins"
        self.plugin_directory.mkdir()
        self.module_name = "engulf_loader_installed_plugins"
        (self.directory / f"{self.module_name}.py").write_text(
            textwrap.dedent(
                """
                from engulf_api import GoalRequirement, Plugin, PluginDependency

                class CatalogPlugin(Plugin):
                    goal_requirement = GoalRequirement("tests.loader.goal", 1)

                    def __init__(self, plugin_id, priority=50):
                        self.plugin_id = plugin_id
                        self.priority = priority

                alpha = CatalogPlugin("tests.loader.alpha", 100)
                beta = CatalogPlugin("tests.loader.beta", 50)
                gamma = CatalogPlugin("tests.loader.gamma", 0)
                transitive = CatalogPlugin("tests.loader.transitive")
                required = CatalogPlugin("tests.loader.required")
                required.plugin_dependencies = (
                    PluginDependency(transitive.plugin_id),
                )
                dependent = CatalogPlugin("tests.loader.dependent")
                dependent.plugin_dependencies = (
                    PluginDependency(required.plugin_id),
                )
                incompatible = CatalogPlugin("tests.loader.incompatible")
                incompatible.goal_requirement = GoalRequirement("tests.other.goal", 1)
                """
            ),
            encoding="utf-8",
        )
        self.addCleanup(sys.modules.pop, self.module_name, None)

    def make_application(
        self,
        *,
        application_id: str = "tests-loader-app",
        policy: PluginPolicy | None = None,
        entries: dict[str, tuple[EntryPoint, ...]] | None = None,
        plugin_dir: Path | None = None,
        discover_installed: bool = True,
        required_plugin_ids: tuple[str, ...] = (),
        plugin_declaration_application_ids: tuple[str, ...] = (),
    ) -> Application:
        mapping = {} if entries is None else entries

        def discover(*, group: str):
            return mapping.get(group, ())

        with (
            patch("engulf.plugin_loader.entry_points", side_effect=discover),
            patch.object(sys, "path", [str(self.directory), *sys.path]),
        ):
            return Application(
                application_id,
                LoaderGoal(),
                display_name="loader-app",
                vendor="Engulf Tests",
                product="Plugin Loader Tests",
                short_product_name="Loader",
                version="0.test",
                plugin_policy=policy,
                required_plugin_ids=required_plugin_ids,
                plugin_declaration_application_ids=(plugin_declaration_application_ids),
                plugin_dir=plugin_dir,
                discover_installed=discover_installed,
            )

    @staticmethod
    def catalog_entry(plugin_id: str, export: str) -> EntryPoint:
        return EntryPoint(
            plugin_id,
            f"engulf_loader_installed_plugins:{export}",
            goal_plugin_entry_point_group(REQUIREMENT.goal_id, REQUIREMENT.api_major),
        )

    @staticmethod
    def application_entry(
        application_id: str,
        plugin_id: str,
        export: str,
    ) -> EntryPoint:
        return EntryPoint(
            plugin_id,
            f"engulf_loader_installed_plugins:{export}",
            application_plugin_entry_point_group(application_id),
        )

    def entries_for(
        self,
        application_id: str,
        *,
        catalog: tuple[EntryPoint, ...],
        declarations: tuple[EntryPoint, ...] = (),
    ) -> dict[str, tuple[EntryPoint, ...]]:
        return {
            goal_plugin_entry_point_group(
                REQUIREMENT.goal_id,
                REQUIREMENT.api_major,
            ): catalog,
            application_plugin_entry_point_group(application_id): declarations,
        }

    def test_identifier_and_entry_point_groups_are_stable(self) -> None:
        self.assertEqual(normalize_application_id("Acme.CLI"), "acme-cli")
        self.assertEqual(
            application_plugin_entry_point_group("Acme.CLI"),
            "engulf.plugins.v1.application.acme_cli",
        )
        self.assertEqual(
            goal_plugin_entry_point_group("tests.loader.goal", 1),
            "engulf.plugins.v1.goal.v1.tests_loader_goal",
        )

    def test_directory_loads_instances_and_factories_in_filename_order(self) -> None:
        (self.plugin_directory / "alpha.py").write_text(
            textwrap.dedent(
                """
                from engulf_api import GoalRequirement, Plugin

                class Alpha(Plugin):
                    plugin_id = "tests.directory.alpha"
                    goal_requirement = GoalRequirement("tests.loader.goal", 1)

                plugin = Alpha
                """
            ),
            encoding="utf-8",
        )
        (self.plugin_directory / "zulu.py").write_text(
            textwrap.dedent(
                """
                from engulf_api import GoalRequirement, Plugin

                class Zulu(Plugin):
                    plugin_id = "tests.directory.zulu"
                    goal_requirement = GoalRequirement("tests.loader.goal", 1)

                plugin = Zulu()
                """
            ),
            encoding="utf-8",
        )

        plugins = load_directory_plugins(self.plugin_directory)

        self.assertEqual(
            [plugin.plugin_id for plugin in plugins],
            ["tests.directory.alpha", "tests.directory.zulu"],
        )

    def test_directory_rejects_invalid_paths_names_and_exports(self) -> None:
        with self.assertRaisesRegex(PluginLoadError, "does not exist"):
            load_directory_plugins(self.directory / "missing")
        invalid = self.plugin_directory / "not-valid-name.py"
        invalid.write_text("plugin = object()\n", encoding="utf-8")
        with self.assertRaisesRegex(PluginLoadError, "valid Python identifier"):
            load_directory_plugins(self.plugin_directory)
        invalid.unlink()

        (self.plugin_directory / "broken.py").write_text(
            "value = 1\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(PluginLoadError, "does not export 'plugin'"):
            load_directory_plugins(self.plugin_directory)

    def test_default_policy_activates_either_side_declaration(self) -> None:
        app_id = "tests-default-app"
        alpha = self.catalog_entry("tests.loader.alpha", "alpha")
        beta = self.catalog_entry("tests.loader.beta", "beta")
        entries = self.entries_for(
            app_id,
            catalog=(alpha, beta),
            declarations=(
                self.application_entry(app_id, "tests.loader.alpha", "alpha"),
            ),
        )

        application = self.make_application(
            application_id=app_id,
            policy=PluginPolicy.declared(include={"tests.loader.beta"}),
            entries=entries,
        )

        self.assertEqual(
            [plugin.plugin_id for plugin in application.plugins],
            ["tests.loader.alpha", "tests.loader.beta"],
        )
        alpha_source = application.plugins[0].source
        self.assertIs(alpha_source.kind, PluginSourceKind.INSTALLED)
        self.assertEqual(
            alpha_source.entry_point_group,
            goal_plugin_entry_point_group(REQUIREMENT.goal_id, REQUIREMENT.api_major),
        )
        self.assertEqual(
            alpha_source.entry_point_value,
            "engulf_loader_installed_plugins:alpha",
        )
        self.assertEqual(alpha_source.target, alpha_source.entry_point_value)

    def test_one_plugin_can_declare_multiple_applications(self) -> None:
        catalog = (self.catalog_entry("tests.loader.alpha", "alpha"),)
        for app_id in ("tests-first-app", "tests-second-app"):
            with self.subTest(application=app_id):
                entries = self.entries_for(
                    app_id,
                    catalog=catalog,
                    declarations=(
                        self.application_entry(
                            app_id,
                            "tests.loader.alpha",
                            "alpha",
                        ),
                    ),
                )
                application = self.make_application(
                    application_id=app_id,
                    entries=entries,
                )
                self.assertEqual(
                    [plugin.plugin_id for plugin in application.plugins],
                    ["tests.loader.alpha"],
                )

    def test_declared_policy_can_inherit_application_declarations(self) -> None:
        base_id = "tests-base-app"
        fork_id = "tests-fork-app"
        alpha = self.catalog_entry("tests.loader.alpha", "alpha")
        entries = self.entries_for(fork_id, catalog=(alpha,))
        entries[application_plugin_entry_point_group(base_id)] = (
            self.application_entry(base_id, "tests.loader.alpha", "alpha"),
        )

        isolated = self.make_application(
            application_id=fork_id,
            entries=entries,
        )
        inherited = self.make_application(
            application_id=fork_id,
            entries=entries,
            plugin_declaration_application_ids=(base_id, base_id),
        )

        self.assertEqual(isolated.plugins, ())
        self.assertEqual(
            [plugin.plugin_id for plugin in inherited.plugins],
            ["tests.loader.alpha"],
        )
        self.assertEqual(
            inherited.plugin_declaration_application_ids,
            (fork_id, base_id),
        )
        self.assertEqual(
            inherited.application_plugin_entry_point_groups,
            (
                application_plugin_entry_point_group(fork_id),
                application_plugin_entry_point_group(base_id),
            ),
        )

    def test_allowlist_and_blocklist_override_plugin_declarations(self) -> None:
        app_id = "tests-policy-app"
        catalog = (
            self.catalog_entry("tests.loader.alpha", "alpha"),
            self.catalog_entry("tests.loader.beta", "beta"),
            self.catalog_entry("tests.loader.gamma", "gamma"),
        )
        declarations = (self.application_entry(app_id, "tests.loader.alpha", "alpha"),)
        entries = self.entries_for(
            app_id,
            catalog=catalog,
            declarations=declarations,
        )

        allowed = self.make_application(
            application_id=app_id,
            policy=PluginPolicy.allow_only({"tests.loader.beta"}),
            entries=entries,
        )
        blocked = self.make_application(
            application_id=app_id,
            policy=PluginPolicy.allow_all_except({"tests.loader.beta"}),
            entries=entries,
        )

        self.assertEqual(
            [plugin.plugin_id for plugin in allowed.plugins],
            ["tests.loader.beta"],
        )
        self.assertEqual(
            [plugin.plugin_id for plugin in blocked.plugins],
            ["tests.loader.alpha", "tests.loader.gamma"],
        )

    def test_allowlist_dependency_activation_is_explicit_by_default(self) -> None:
        required = LoaderPlugin("tests.loader.required")
        dependent = LoaderPlugin(
            "tests.loader.dependent",
            dependencies=(PluginDependency(required.plugin_id),),
        )
        with (
            patch(
                "engulf.application.load_directory_plugins",
                return_value=(dependent, required),
            ),
            self.assertRaisesRegex(PluginDependencyError, "requires missing plugin"),
        ):
            self.make_application(
                policy=PluginPolicy.allow_only({dependent.plugin_id}),
                plugin_dir=self.plugin_directory,
                discover_installed=False,
            )

    def test_allowlist_can_activate_transitive_dependencies_across_sources(
        self,
    ) -> None:
        dependent_id = "tests.loader.dependent"
        required_id = "tests.loader.required"
        transitive_id = "tests.loader.transitive"
        local_required = LoaderPlugin(
            required_id,
            dependencies=(PluginDependency(transitive_id),),
        )
        entries = self.entries_for(
            "tests-loader-app",
            catalog=(
                self.catalog_entry(dependent_id, "dependent"),
                self.catalog_entry(transitive_id, "transitive"),
            ),
        )

        with patch(
            "engulf.application.load_directory_plugins",
            return_value=(local_required,),
        ):
            application = self.make_application(
                policy=PluginPolicy.allow_only(
                    {dependent_id},
                    include_dependencies=True,
                ),
                entries=entries,
                plugin_dir=self.plugin_directory,
            )

        self.assertEqual(
            [plugin.plugin_id for plugin in application.plugins],
            [transitive_id, required_id, dependent_id],
        )

    def test_implicit_allowlist_still_rejects_unavailable_dependencies(self) -> None:
        dependent = LoaderPlugin(
            "tests.loader.dependent",
            dependencies=(PluginDependency("tests.loader.unavailable"),),
        )
        with (
            patch(
                "engulf.application.load_directory_plugins",
                return_value=(dependent,),
            ),
            self.assertRaisesRegex(PluginDependencyError, "requires missing plugin"),
        ):
            self.make_application(
                policy=PluginPolicy.allow_only(
                    {dependent.plugin_id},
                    include_dependencies=True,
                ),
                plugin_dir=self.plugin_directory,
                discover_installed=False,
            )

    def test_dependency_activation_policy_validation(self) -> None:
        with self.assertRaisesRegex(TypeError, "must be a boolean"):
            PluginPolicy.allow_only(
                {"tests.loader.alpha"},
                include_dependencies=1,  # type: ignore[arg-type]
            )
        with self.assertRaisesRegex(ValueError, "only by allowlist"):
            PluginPolicy(
                PluginPolicyMode.DECLARED,
                frozenset(),
                include_dependencies=True,
            )

    def test_policy_including_only_expands_the_selected_set(self) -> None:
        declared = PluginPolicy.declared(include={"tests.loader.alpha"}).including(
            {"tests.loader.beta"}
        )
        allowlist = PluginPolicy.allow_only(
            {"tests.loader.alpha"},
            include_dependencies=True,
        ).including({"tests.loader.beta"})
        blocklist = PluginPolicy.allow_all_except(
            {"tests.loader.alpha", "tests.loader.beta"}
        ).including({"tests.loader.beta"})

        self.assertEqual(
            declared.plugin_ids,
            frozenset({"tests.loader.alpha", "tests.loader.beta"}),
        )
        self.assertEqual(
            allowlist.plugin_ids,
            frozenset({"tests.loader.alpha", "tests.loader.beta"}),
        )
        self.assertTrue(allowlist.include_dependencies)
        self.assertEqual(blocklist.plugin_ids, frozenset({"tests.loader.alpha"}))

    def test_missing_explicit_ids_are_optional(self) -> None:
        application = self.make_application(
            policy=PluginPolicy.allow_only({"tests.loader.missing"}),
            entries={},
        )
        self.assertEqual(application.plugins, ())
        self.assertEqual(
            application.missing_policy_ids,
            ("tests.loader.missing",),
        )

    def test_required_ids_are_selected_and_missing_ids_fail(self) -> None:
        app_id = "tests-required-app"
        alpha = self.catalog_entry("tests.loader.alpha", "alpha")
        selected = self.make_application(
            application_id=app_id,
            entries=self.entries_for(app_id, catalog=(alpha,)),
            required_plugin_ids=("tests.loader.alpha",),
        )

        self.assertEqual(
            [plugin.plugin_id for plugin in selected.plugins],
            ["tests.loader.alpha"],
        )
        self.assertEqual(
            selected.required_plugin_ids,
            frozenset({"tests.loader.alpha"}),
        )
        self.assertEqual(selected.missing_policy_ids, ())

        with self.assertRaisesRegex(
            PluginRequirementError,
            "required plugins are unavailable.*tests.loader.missing",
        ):
            self.make_application(
                application_id=app_id,
                entries=self.entries_for(app_id, catalog=()),
                required_plugin_ids=("tests.loader.missing",),
            )

    def test_unselected_catalog_entry_is_not_imported(self) -> None:
        marker = self.directory / "imported"
        module = self.directory / "unselected_plugin.py"
        module.write_text(
            textwrap.dedent(
                f"""
                from pathlib import Path
                Path({str(marker)!r}).write_text("imported", encoding="utf-8")
                """
            ),
            encoding="utf-8",
        )
        group = goal_plugin_entry_point_group(
            REQUIREMENT.goal_id,
            REQUIREMENT.api_major,
        )
        entries = {
            group: (
                EntryPoint(
                    "tests.loader.unselected",
                    "unselected_plugin:plugin",
                    group,
                ),
            ),
        }

        self.make_application(
            policy=PluginPolicy.allow_only(()),
            entries=entries,
        )

        self.assertFalse(marker.exists())

    def test_application_policy_cannot_override_goal_compatibility(self) -> None:
        app_id = "tests-incompatible-app"
        entry = self.catalog_entry(
            "tests.loader.incompatible",
            "incompatible",
        )
        entries = self.entries_for(app_id, catalog=(entry,))
        with self.assertRaisesRegex(PluginLoadError, "requires goal"):
            self.make_application(
                application_id=app_id,
                policy=PluginPolicy.allow_only({"tests.loader.incompatible"}),
                entries=entries,
            )

    def test_duplicate_catalog_ids_and_mismatched_declarations_fail(self) -> None:
        app_id = "tests-invalid-catalog"
        alpha = self.catalog_entry("tests.loader.alpha", "alpha")
        duplicate = EntryPoint(
            "tests.loader.alpha",
            f"{self.module_name}:beta",
            alpha.group,
        )
        with self.assertRaisesRegex(PluginLoadError, "duplicate plugin ID"):
            self.make_application(
                application_id=app_id,
                entries=self.entries_for(app_id, catalog=(alpha, duplicate)),
            )

        mismatch = self.application_entry(
            app_id,
            "tests.loader.alpha",
            "beta",
        )
        with self.assertRaisesRegex(PluginLoadError, "does not match"):
            self.make_application(
                application_id=app_id,
                entries=self.entries_for(
                    app_id,
                    catalog=(alpha,),
                    declarations=(mismatch,),
                ),
            )

    def test_dependency_validation_still_applies_after_policy(self) -> None:
        required = LoaderPlugin("tests.loader.required")
        dependent = LoaderPlugin(
            "tests.loader.dependent",
            dependencies=(PluginDependency(required.plugin_id),),
        )
        with (
            patch(
                "engulf.application.load_directory_plugins",
                return_value=(dependent, required),
            ),
            self.assertRaisesRegex(PluginDependencyError, "requires missing plugin"),
        ):
            Application(
                "tests-directory-policy",
                LoaderGoal(),
                display_name="loader-app",
                vendor="Engulf Tests",
                product="Plugin Loader Tests",
                short_product_name="Loader",
                version="0.test",
                plugin_policy=PluginPolicy.allow_only({dependent.plugin_id}),
                plugin_dir=self.plugin_directory,
                discover_installed=False,
            )

    def test_public_packages_do_not_export_old_wrapper_contracts(self) -> None:
        self.assertIs(engulf.Application, Application)
        self.assertFalse(hasattr(engulf, "Engulf"))
        self.assertFalse(hasattr(engulf, "Plugin"))


if __name__ == "__main__":
    unittest.main()
