from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from importlib.metadata import EntryPoint
from pathlib import Path
from unittest.mock import patch

from engulf_api import Plugin

import engulf
from engulf import Engulf, PluginLoadError, plugin_entry_point_group


class PluginLoaderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)
        self.plugin_directory = self.directory / "plugins"
        self.plugin_directory.mkdir()

    def write_plugin(self, name: str, source: str) -> Path:
        path = self.plugin_directory / name
        path.write_text(textwrap.dedent(source), encoding="utf-8")
        return path

    def local_app(self, plugin_dir: Path | None = None) -> Engulf:
        return Engulf(
            "echo",
            "engulf-loader-tests",
            plugin_dir=self.plugin_directory if plugin_dir is None else plugin_dir,
            discover_installed=False,
        )

    def test_loads_instances_and_factories_in_filename_order(self) -> None:
        self.write_plugin("_helper.py", 'VALUE = "from helper"\n')
        self.write_plugin(
            "a_factory.py",
            """
            from engulf_api import Plugin
            from ._helper import VALUE

            class FactoryPlugin(Plugin):
                plugin_id = "tests.loader.factory"

                def help(self):
                    return f"factory {VALUE}"

            def plugin():
                return FactoryPlugin()
            """,
        )
        self.write_plugin(
            "b_instance.py",
            """
            from engulf_api import Plugin

            class InstancePlugin(Plugin):
                plugin_id = "tests.loader.instance"

                def help(self):
                    return "instance"

            plugin = InstancePlugin()
            """,
        )

        app = self.local_app()

        self.assertEqual(
            [plugin.help() for plugin in app.plugins],
            ["factory from helper", "instance"],
        )
        self.assertEqual(app.plugin_directory, self.plugin_directory.resolve())

    def test_private_modules_and_init_are_not_plugin_entries(self) -> None:
        self.write_plugin("__init__.py", 'raise RuntimeError("must not execute")\n')
        self.write_plugin("_private.py", 'raise RuntimeError("must not execute")\n')

        self.assertEqual(self.local_app().plugins, ())

    def test_empty_directory_is_valid(self) -> None:
        self.assertEqual(self.local_app().plugins, ())

    def test_rejects_missing_and_non_directory_paths(self) -> None:
        missing = self.directory / "missing"
        regular_file = self.directory / "file"
        regular_file.write_text("", encoding="utf-8")

        with self.assertRaisesRegex(PluginLoadError, "does not exist"):
            self.local_app(missing)
        with self.assertRaisesRegex(PluginLoadError, "not a directory"):
            self.local_app(regular_file)

    def test_rejects_invalid_plugin_filename(self) -> None:
        self.write_plugin("bad-name.py", "plugin = None\n")

        with self.assertRaisesRegex(PluginLoadError, "valid Python identifier"):
            self.local_app()

    def test_rejects_module_without_plugin_export(self) -> None:
        path = self.write_plugin("missing_export.py", "VALUE = 1\n")

        with self.assertRaisesRegex(
            PluginLoadError, "does not export 'plugin'"
        ) as caught:
            self.local_app()
        self.assertIn(str(path), str(caught.exception))

    def test_rejects_invalid_plugin_exports(self) -> None:
        invalid_sources = {
            "not_callable.py": "plugin = 3\n",
            "bad_factory.py": "def plugin():\n    return object()\n",
        }

        for name, source in invalid_sources.items():
            with self.subTest(name=name):
                path = self.write_plugin(name, source)
                expected = (
                    "zero-argument factory"
                    if name == "not_callable.py"
                    else "did not return a Plugin"
                )
                with self.assertRaisesRegex(PluginLoadError, expected):
                    self.local_app()
                path.unlink()

    def test_rejects_non_integer_priority(self) -> None:
        self.write_plugin(
            "invalid_priority.py",
            """
            from engulf_api import Plugin

            class InvalidPriorityPlugin(Plugin):
                plugin_id = "tests.loader.invalid_priority"
                priority = True

                def help(self):
                    return "invalid"

            plugin = InvalidPriorityPlugin()
            """,
        )

        with self.assertRaisesRegex(PluginLoadError, "priority.*must be an integer"):
            self.local_app()

    def test_wraps_import_and_factory_failures(self) -> None:
        failures = {
            "import_failure.py": (
                'raise RuntimeError("import failed")\n',
                "failed to import",
            ),
            "factory_failure.py": (
                'def plugin():\n    raise RuntimeError("factory failed")\n',
                "factory failed",
            ),
        }

        for name, (source, expected) in failures.items():
            with self.subTest(name=name):
                path = self.write_plugin(name, source)
                with self.assertRaisesRegex(PluginLoadError, expected) as caught:
                    self.local_app()
                self.assertIsInstance(caught.exception.__cause__, RuntimeError)
                path.unlink()

    def test_discovers_installed_plugins_for_normalized_application(self) -> None:
        module = self.directory / "installed_plugins.py"
        module.write_text(
            textwrap.dedent(
                """
                from engulf_api import Plugin

                class AlphaPlugin(Plugin):
                    plugin_id = "tests.loader.alpha"
                    priority = -1

                    def help(self):
                        return "alpha"

                class ZuluPlugin(Plugin):
                    plugin_id = "tests.loader.zulu"
                    priority = 20

                    def help(self):
                        return "zulu"

                alpha = AlphaPlugin
                zulu = ZuluPlugin()
                """
            ),
            encoding="utf-8",
        )
        group = "engulf.plugins.v1.acme_cli"
        entries = (
            EntryPoint("zulu", "installed_plugins:zulu", group),
            EntryPoint("alpha", "installed_plugins:alpha", group),
        )

        with (
            patch(
                "engulf.plugin_loader.entry_points", return_value=entries
            ) as discover,
            patch.object(sys, "path", [str(self.directory), *sys.path]),
        ):
            app = Engulf("echo", "Acme.CLI")

        self.addCleanup(sys.modules.pop, "installed_plugins", None)
        discover.assert_called_once_with(group=group)
        self.assertEqual(app.application_id, "acme-cli")
        self.assertEqual(app.plugin_entry_point_group, group)
        self.assertIsNone(app.plugin_directory)
        self.assertEqual([plugin.help() for plugin in app.plugins], ["zulu", "alpha"])

    def test_installed_plugin_load_failure_has_entry_point_context(self) -> None:
        group = plugin_entry_point_group("broken-app")
        entry = EntryPoint("broken", "missing_engulf_plugin:plugin", group)

        with (
            patch("engulf.plugin_loader.entry_points", return_value=(entry,)),
            self.assertRaisesRegex(PluginLoadError, "broken") as caught,
        ):
            Engulf("echo", "broken-app")

        self.assertIsInstance(caught.exception.__cause__, ModuleNotFoundError)

    def test_rejects_invalid_application_identifier(self) -> None:
        with self.assertRaisesRegex(ValueError, "application_id"):
            Engulf("echo", "not an application!", discover_installed=False)

    def test_public_packages_have_separate_responsibilities(self) -> None:
        self.assertIs(engulf.Engulf, Engulf)
        self.assertFalse(hasattr(engulf, "Plugin"))
        self.assertFalse(hasattr(engulf, "Wrapper"))
        self.assertTrue(issubclass(Plugin, object))


if __name__ == "__main__":
    unittest.main()
