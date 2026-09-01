from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr
from importlib.metadata import EntryPoint
from pathlib import Path
from unittest.mock import patch

from engulf.packaging_check import check_projects, main

from engulf import PluginLoadError, goal_plugin_entry_point_group

CATALOG_GROUP = goal_plugin_entry_point_group("tests.packaging.goal", 1)

PROJECT = """
[project]
name = "example-audit"
version = "0.1.0"
dependencies = [{dependencies}]

[project.entry-points."engulf.plugins.v1.dependency.com_example_audit"]
{declarations}
"""


class _Distribution:
    def __init__(self, name: str) -> None:
        self.name = name
        self.version = "1.0"


class PackagingCheckTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)

    def write_project(self, *, dependencies: str, declarations: str) -> Path:
        project = self.directory / "example-audit"
        project.mkdir(exist_ok=True)
        (project / "pyproject.toml").write_text(
            PROJECT.format(dependencies=dependencies, declarations=declarations),
            encoding="utf-8",
        )
        return project

    @staticmethod
    def installed(*plugins: tuple[str, str]) -> tuple[EntryPoint, ...]:
        return tuple(
            EntryPoint(plugin_id, "example:plugin", CATALOG_GROUP)._for(
                _Distribution(distribution)
            )
            for plugin_id, distribution in plugins
        )

    def test_declared_provider_must_be_a_project_dependency(self) -> None:
        project = self.write_project(
            dependencies='"engulf-api>=1.1,<2"',
            declarations='"com.example.schema" = "preprocess=before; postprocess=after"',
        )

        with patch(
            "engulf.packaging_check.entry_points",
            return_value=self.installed(("com.example.schema", "example-schema")),
        ):
            findings = check_projects((project,))

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].project, "example-audit")
        self.assertEqual(findings[0].dependency_id, "com.example.schema")
        self.assertIn("example-schema", findings[0].message)
        self.assertIn("missing from the project's dependencies", findings[0].message)

    def test_declared_provider_present_in_dependencies_passes(self) -> None:
        project = self.write_project(
            dependencies='"engulf-api>=1.1,<2", "Example_Schema >= 2, < 3"',
            declarations='"com.example.schema" = "preprocess=before; postprocess=after"',
        )

        with patch(
            "engulf.packaging_check.entry_points",
            return_value=self.installed(("com.example.schema", "example-schema")),
        ):
            self.assertEqual(check_projects((project,)), ())

    def test_a_plugin_from_the_same_distribution_needs_no_requirement(self) -> None:
        project = self.write_project(
            dependencies="",
            declarations='"com.example.schema" = "preprocess=before; postprocess=after"',
        )

        with patch(
            "engulf.packaging_check.entry_points",
            return_value=self.installed(("com.example.schema", "example-audit")),
        ):
            self.assertEqual(check_projects((project,)), ())

    def test_unresolvable_dependency_is_reported_not_silently_passed(self) -> None:
        project = self.write_project(
            dependencies="",
            declarations='"com.example.schema" = "preprocess=before; postprocess=after"',
        )

        with patch("engulf.packaging_check.entry_points", return_value=()):
            findings = check_projects((project,))

        self.assertEqual(len(findings), 1)
        self.assertIn("cannot verify", findings[0].message)

    def test_invalid_ordering_and_unreadable_projects_are_errors(self) -> None:
        project = self.write_project(
            dependencies="",
            declarations=(
                '"com.example.schema" = "preprocess=sideways; postprocess=after"'
            ),
        )

        with (
            patch("engulf.packaging_check.entry_points", return_value=()),
            self.assertRaisesRegex(PluginLoadError, "must be 'before', 'after'"),
        ):
            check_projects((project,))

        with self.assertRaisesRegex(PluginLoadError, "cannot read"):
            check_projects((self.directory / "absent",))

    def test_main_reports_findings_and_usage(self) -> None:
        project = self.write_project(
            dependencies="",
            declarations='"com.example.schema" = "preprocess=before; postprocess=after"',
        )

        stderr = io.StringIO()
        with (
            patch(
                "engulf.packaging_check.entry_points",
                return_value=self.installed(("com.example.schema", "example-schema")),
            ),
            redirect_stderr(stderr),
        ):
            self.assertEqual(main([str(project)]), 1)
        self.assertIn("example-schema", stderr.getvalue())

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(main([]), 2)
        self.assertIn("usage:", stderr.getvalue())

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(main([str(self.directory / "absent")]), 2)
        self.assertIn("error:", stderr.getvalue())

    def test_projects_without_plugin_dependencies_pass(self) -> None:
        project = self.directory / "plain"
        project.mkdir()
        (project / "pyproject.toml").write_text(
            '[project]\nname = "plain"\nversion = "0.1.0"\n',
            encoding="utf-8",
        )

        with patch("engulf.packaging_check.entry_points", return_value=()):
            self.assertEqual(check_projects((project,)), ())


if __name__ == "__main__":
    unittest.main()
