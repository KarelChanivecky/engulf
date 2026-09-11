from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import textwrap
import unittest
from importlib.metadata import EntryPoint
from pathlib import Path
from unittest.mock import patch

from engulf.plugin_loader import (
    EntryPointIndex,
    load_directory_plugins,
    normalize_application_id,
)
from engulf_api import (
    DependencyPosition,
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
    diagnostic_entry_point_group,
    diagnostic_trigger_entry_point_group,
    goal_plugin_entry_point_group,
    plugin_dependency_entry_point_group,
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

    def __init__(self, plugin_id: str, *, priority: int = 50) -> None:
        self.plugin_id = plugin_id
        self.priority = priority


class _CountingDistribution:
    def __init__(
        self,
        name: str,
        version: str,
        requires: list[str] | None = None,
    ) -> None:
        self._name = name
        self._version = version
        self.requires = requires
        self.name_reads = 0
        self.version_reads = 0

    @property
    def name(self) -> str:
        self.name_reads += 1
        return self._name

    @property
    def version(self) -> str:
        self.version_reads += 1
        return self._version


class PluginLoaderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        elevation = patch("engulf.application.is_process_elevated", return_value=False)
        elevation.start()
        self.addCleanup(elevation.stop)
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)
        self.plugin_directory = self.directory / "plugins"
        self.plugin_directory.mkdir()
        self.module_name = "engulf_loader_installed_plugins"
        (self.directory / f"{self.module_name}.py").write_text(
            textwrap.dedent(
                """
                from engulf_api import GoalRequirement, Plugin

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
                dependent = CatalogPlugin("tests.loader.dependent")
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

        def discover():
            return tuple(
                entry_point
                for group_entries in mapping.values()
                for entry_point in group_entries
            )

        with (
            patch(
                "engulf.plugin_loader.entry_points",
                side_effect=discover,
            ) as snapshot,
            patch.object(sys, "path", [str(self.directory), *sys.path]),
        ):
            application = Application(
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
        if discover_installed:
            snapshot.assert_called_once_with()
        else:
            snapshot.assert_not_called()
        return application

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

    @staticmethod
    def dependency_entries(
        plugin_id: str,
        dependencies: dict[str, str],
    ) -> tuple[EntryPoint, ...]:
        group = plugin_dependency_entry_point_group(plugin_id)
        return tuple(
            EntryPoint(dependency_id, ordering, group)
            for dependency_id, ordering in dependencies.items()
        )

    def entries_for(
        self,
        application_id: str,
        *,
        catalog: tuple[EntryPoint, ...],
        declarations: tuple[EntryPoint, ...] = (),
        dependencies: dict[str, dict[str, str]] | None = None,
    ) -> dict[str, tuple[EntryPoint, ...]]:
        entries = {
            goal_plugin_entry_point_group(
                REQUIREMENT.goal_id,
                REQUIREMENT.api_major,
            ): catalog,
            application_plugin_entry_point_group(application_id): declarations,
        }
        for plugin_id, mapping in (dependencies or {}).items():
            entries[plugin_dependency_entry_point_group(plugin_id)] = (
                self.dependency_entries(plugin_id, mapping)
            )
        return entries

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

    def test_entry_point_index_snapshots_once_and_caches_distribution_metadata(
        self,
    ) -> None:
        goal_group = goal_plugin_entry_point_group(
            REQUIREMENT.goal_id,
            REQUIREMENT.api_major,
        )
        application_group = application_plugin_entry_point_group("tests-index-app")
        distribution = _CountingDistribution("Tests.Distribution", "1.2.3")
        goal_entry = EntryPoint(
            "tests.loader.alpha",
            f"{self.module_name}:alpha",
            goal_group,
        )._for(distribution)
        declaration = EntryPoint(
            "tests.loader.alpha",
            f"{self.module_name}:alpha",
            application_group,
        )._for(distribution)
        unrelated_distribution = _CountingDistribution("Unrelated", "9")
        unrelated = EntryPoint(
            "tests.unrelated.plugin",
            "unrelated:plugin",
            "tests.unrelated.group",
        )._for(unrelated_distribution)

        with patch(
            "engulf.plugin_loader.entry_points",
            return_value=(goal_entry, declaration, unrelated),
        ) as snapshot:
            index = EntryPointIndex.discover((goal_group, application_group))

        snapshot.assert_called_once_with()
        self.assertEqual(index.entries(goal_group), (goal_entry,))
        self.assertEqual(index.entries(application_group), (declaration,))
        first_identity = index.distribution_identity(goal_entry)
        self.assertIs(index.distribution_identity(goal_entry), first_identity)
        self.assertIs(index.distribution_identity(declaration), first_identity)
        self.assertEqual(first_identity.name, "Tests.Distribution")
        self.assertEqual(first_identity.normalized_name, "tests-distribution")
        self.assertEqual(first_identity.version, "1.2.3")
        self.assertEqual(distribution.name_reads, 1)
        self.assertEqual(distribution.version_reads, 1)
        self.assertEqual(unrelated_distribution.name_reads, 0)
        self.assertEqual(unrelated_distribution.version_reads, 0)

    def test_application_shares_one_snapshot_across_all_entry_point_groups(
        self,
    ) -> None:
        application_id = "tests-index-app"
        catalog = self.catalog_entry("tests.loader.alpha", "alpha")
        entries = self.entries_for(
            application_id,
            catalog=(catalog,),
            declarations=(
                self.application_entry(
                    application_id,
                    "tests.loader.alpha",
                    "alpha",
                ),
            ),
        )
        diagnostic_group = diagnostic_entry_point_group(
            REQUIREMENT.goal_id,
            REQUIREMENT.api_major,
        )
        trigger_group = diagnostic_trigger_entry_point_group(
            REQUIREMENT.goal_id,
            REQUIREMENT.api_major,
        )
        entries[diagnostic_group] = (
            EntryPoint(
                "tests.diagnostic.inventory",
                "never_import_inventory:diagnostic",
                diagnostic_group,
            ),
        )
        entries[trigger_group] = (
            EntryPoint(
                "--inventory",
                "never_import_inventory:diagnostic",
                trigger_group,
            ),
        )

        application = self.make_application(
            application_id=application_id,
            entries=entries,
        )

        self.assertEqual(
            tuple(plugin.plugin_id for plugin in application.plugins),
            ("tests.loader.alpha",),
        )
        self.assertEqual(
            tuple(
                extension.diagnostic_id
                for extension in application.diagnostic_extensions
            ),
            ("tests.diagnostic.inventory",),
        )
        self.assertNotIn("never_import_inventory", sys.modules)
        application.close()

    def test_disabled_installed_discovery_does_not_take_a_snapshot(self) -> None:
        application = self.make_application(discover_installed=False)

        self.assertEqual(application.plugins, ())
        self.assertEqual(application.diagnostic_extensions, ())
        application.close()

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
        dependent_id = "tests.loader.dependent"
        required_id = "tests.loader.required"
        entries = self.entries_for(
            "tests-loader-app",
            catalog=(
                self.catalog_entry(dependent_id, "dependent"),
                self.catalog_entry(required_id, "required"),
            ),
            dependencies={
                dependent_id: {required_id: "preprocess=before; postprocess=after"}
            },
        )

        with self.assertRaisesRegex(PluginDependencyError, "requires missing plugin"):
            self.make_application(
                policy=PluginPolicy.allow_only({dependent_id}),
                entries=entries,
            )

    def test_allowlist_can_activate_transitive_dependencies(self) -> None:
        dependent_id = "tests.loader.dependent"
        required_id = "tests.loader.required"
        transitive_id = "tests.loader.transitive"
        entries = self.entries_for(
            "tests-loader-app",
            catalog=(
                self.catalog_entry(dependent_id, "dependent"),
                self.catalog_entry(required_id, "required"),
                self.catalog_entry(transitive_id, "transitive"),
            ),
            dependencies={
                dependent_id: {required_id: "preprocess=before; postprocess=after"},
                required_id: {transitive_id: "preprocess=before; postprocess=after"},
            },
        )

        application = self.make_application(
            policy=PluginPolicy.allow_only(
                {dependent_id},
                include_dependencies=True,
            ),
            entries=entries,
        )

        self.assertEqual(
            [plugin.plugin_id for plugin in application.plugins],
            [transitive_id, required_id, dependent_id],
        )

    def test_implicit_allowlist_still_rejects_unavailable_dependencies(self) -> None:
        dependent_id = "tests.loader.dependent"
        entries = self.entries_for(
            "tests-loader-app",
            catalog=(self.catalog_entry(dependent_id, "dependent"),),
            dependencies={
                dependent_id: {
                    "tests.loader.unavailable": "preprocess=before; postprocess=after"
                }
            },
        )

        with self.assertRaisesRegex(PluginDependencyError, "requires missing plugin"):
            self.make_application(
                policy=PluginPolicy.allow_only(
                    {dependent_id},
                    include_dependencies=True,
                ),
                entries=entries,
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
        dependent_id = "tests.loader.dependent"
        required_id = "tests.loader.required"
        entries = self.entries_for(
            "tests-loader-app",
            catalog=(
                self.catalog_entry(dependent_id, "dependent"),
                self.catalog_entry(required_id, "required"),
            ),
            declarations=(
                self.application_entry("tests-loader-app", dependent_id, "dependent"),
                self.application_entry("tests-loader-app", required_id, "required"),
            ),
            dependencies={
                dependent_id: {required_id: "preprocess=before; postprocess=after"}
            },
        )

        with self.assertRaisesRegex(PluginDependencyError, "requires missing plugin"):
            self.make_application(
                policy=PluginPolicy.allow_all_except({required_id}),
                entries=entries,
            )

    def test_code_declared_dependencies_are_rejected(self) -> None:
        plugin = LoaderPlugin("tests.loader.legacy")
        plugin.plugin_dependencies = (  # type: ignore[attr-defined]
            PluginDependency(
                "tests.loader.required",
                DependencyPosition.BEFORE,
                DependencyPosition.AFTER,
            ),
        )
        with (
            patch(
                "engulf.application.load_directory_plugins",
                return_value=(plugin,),
            ),
            self.assertRaisesRegex(
                PluginDependencyError,
                "declares plugin_dependencies in code",
            ),
        ):
            self.make_application(
                plugin_dir=self.plugin_directory,
                discover_installed=False,
            )

    def test_dependency_declarations_are_parsed_and_validated(self) -> None:
        dependent_id = "tests.loader.dependent"
        required_id = "tests.loader.required"
        catalog = (
            self.catalog_entry(dependent_id, "dependent"),
            self.catalog_entry(required_id, "required"),
        )
        declarations = (
            self.application_entry("tests-loader-app", dependent_id, "dependent"),
            self.application_entry("tests-loader-app", required_id, "required"),
        )

        application = self.make_application(
            entries=self.entries_for(
                "tests-loader-app",
                catalog=catalog,
                declarations=declarations,
                dependencies={
                    dependent_id: {required_id: "preprocess=none; postprocess=before"}
                },
            ),
        )
        active = {plugin.plugin_id: plugin for plugin in application.plugins}
        self.assertEqual(
            active[dependent_id].dependencies,
            (PluginDependency(required_id, None, DependencyPosition.BEFORE),),
        )
        self.assertEqual(active[required_id].dependencies, ())

        for ordering, message in (
            ("preprocess=none; postprocess=none", "must order it in the preprocess"),
            ("preprocess=before", "must declare 'postprocess'"),
            ("before/after", "'<field>=<value>' pairs"),
            ("preprocess=sideways; postprocess=after", "must be 'before', 'after'"),
            (
                "preprocess=before; postprocess=after; version=1",
                "unknown field 'version'",
            ),
            (
                "preprocess=before; preprocess=after; postprocess=after",
                "declares 'preprocess' more than once",
            ),
        ):
            with (
                self.subTest(ordering=ordering),
                self.assertRaisesRegex(PluginDependencyError, message),
            ):
                self.make_application(
                    entries=self.entries_for(
                        "tests-loader-app",
                        catalog=catalog,
                        declarations=declarations,
                        dependencies={dependent_id: {required_id: ordering}},
                    ),
                )

    def test_repeated_dependency_declarations_are_rejected(self) -> None:
        dependent_id = "tests.loader.dependent"
        required_id = "tests.loader.required"
        group = plugin_dependency_entry_point_group(dependent_id)
        entries = self.entries_for(
            "tests-loader-app",
            catalog=(
                self.catalog_entry(dependent_id, "dependent"),
                self.catalog_entry(required_id, "required"),
            ),
        )
        entries[group] = (
            EntryPoint(required_id, "preprocess=before; postprocess=after", group),
            EntryPoint(required_id, "preprocess=none; postprocess=after", group),
        )

        with self.assertRaisesRegex(PluginDependencyError, "more than once"):
            self.make_application(entries=entries)

    def test_dependency_declarations_must_come_from_the_providing_distribution(
        self,
    ) -> None:
        dependent_id = "tests.loader.dependent"
        required_id = "tests.loader.required"
        provider = _CountingDistribution("provider-dist", "1.0")
        foreign = _CountingDistribution("foreign-dist", "1.0")
        catalog = (
            EntryPoint(
                dependent_id,
                f"{self.module_name}:dependent",
                goal_plugin_entry_point_group(
                    REQUIREMENT.goal_id,
                    REQUIREMENT.api_major,
                ),
            )._for(provider),
            EntryPoint(
                required_id,
                f"{self.module_name}:required",
                goal_plugin_entry_point_group(
                    REQUIREMENT.goal_id,
                    REQUIREMENT.api_major,
                ),
            )._for(provider),
        )
        group = plugin_dependency_entry_point_group(dependent_id)
        entries = self.entries_for("tests-loader-app", catalog=catalog)
        entries[group] = (
            EntryPoint(required_id, "preprocess=before; postprocess=after", group)._for(
                foreign
            ),
        )

        with self.assertRaisesRegex(
            PluginLoadError,
            "does not come from the distribution providing",
        ):
            self.make_application(
                policy=PluginPolicy.allow_all_except(()),
                entries=entries,
            )

    def test_dependency_provider_missing_from_requirements_warns_once(self) -> None:
        dependent_id = "tests.loader.dependent"
        required_id = "tests.loader.required"
        catalog_group = goal_plugin_entry_point_group(
            REQUIREMENT.goal_id,
            REQUIREMENT.api_major,
        )
        dependent_dist = _CountingDistribution("example-audit", "1.0", requires=[])
        provider_dist = _CountingDistribution("example-schema", "2.0", requires=[])
        catalog = (
            EntryPoint(
                dependent_id,
                f"{self.module_name}:dependent",
                catalog_group,
            )._for(dependent_dist),
            EntryPoint(
                required_id,
                f"{self.module_name}:required",
                catalog_group,
            )._for(provider_dist),
        )
        group = plugin_dependency_entry_point_group(dependent_id)
        entries = self.entries_for("tests-loader-app", catalog=catalog)
        entries[group] = (
            EntryPoint(required_id, "preprocess=before; postprocess=after", group)._for(
                dependent_dist
            ),
        )

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            application = self.make_application(
                policy=PluginPolicy.allow_all_except(()),
                entries=entries,
            )
            self.assertEqual(application.run([]), 0)
        output = stderr.getvalue()

        self.assertIn("example-schema", output)
        self.assertIn("does not declare in its distribution requirements", output)
        self.assertEqual(output.count("example-schema"), 1)

        dependent_dist.requires = ["example-schema>=2,<3"]
        quiet = io.StringIO()
        with contextlib.redirect_stderr(quiet):
            satisfied = self.make_application(
                policy=PluginPolicy.allow_all_except(()),
                entries=entries,
            )
            self.assertEqual(satisfied.run([]), 0)
        self.assertNotIn("distribution requirements", quiet.getvalue())

    def test_public_packages_do_not_export_old_wrapper_contracts(self) -> None:
        self.assertIs(engulf.Application, Application)
        self.assertFalse(hasattr(engulf, "Engulf"))
        self.assertFalse(hasattr(engulf, "Plugin"))


if __name__ == "__main__":
    unittest.main()
