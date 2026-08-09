from __future__ import annotations

import unittest

from engulf_api import (
    PLUGIN_API_MAJOR,
    PLUGIN_API_VERSION,
    ArgumentRegistry,
    CompletionCandidate,
    CompletionContext,
    CompletionRegistry,
    DependencyPosition,
    Plugin,
    PluginAPI,
    PluginDependency,
    Shell,
    validate_global_identifier,
)


class ExamplePlugin(Plugin):
    plugin_id = "tests.api.example"

    def help(self) -> str:
        return "example"


class ApiTestCase(unittest.TestCase):
    def test_api_version_matches_contract(self) -> None:
        self.assertEqual(PLUGIN_API_MAJOR, 1)
        self.assertEqual(PLUGIN_API_VERSION, "1.2.0")

    def test_plugin_priority_defaults_to_fifty_and_can_be_overridden(self) -> None:
        class EarlierPlugin(ExamplePlugin):
            priority = 25

        self.assertEqual(ExamplePlugin().priority, 50)
        self.assertEqual(EarlierPlugin().priority, 25)

    def test_plugin_requires_help_implementation(self) -> None:
        class IncompletePlugin(Plugin):
            pass

        with self.assertRaises(TypeError):
            IncompletePlugin()
        self.assertEqual(ExamplePlugin().help(), "example")

    def test_plugin_metadata_defaults(self) -> None:
        plugin = ExamplePlugin()

        self.assertEqual(plugin.plugin_dependencies, ())
        self.assertEqual(plugin.context_reads, frozenset())
        self.assertEqual(plugin.context_writes, frozenset())

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

    def test_plugin_api_is_abstract(self) -> None:
        with self.assertRaises(TypeError):
            PluginAPI()

    def test_argument_registry_rejects_duplicate_options(self) -> None:
        registry = ArgumentRegistry()
        registry.option("--one")

        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.option("--one")

    def test_completion_registry_accepts_candidates_and_providers(self) -> None:
        registry = CompletionRegistry()
        registry.candidate("--static")
        registry.provider(lambda context: [CompletionCandidate("--dynamic")])
        context = CompletionContext(
            Shell.BASH,
            "example",
            "binary",
            ("--",),
            0,
        )

        self.assertEqual(
            [candidate.value for candidate in registry.static_candidates(context)],
            ["--static"],
        )
        self.assertEqual(len(registry.providers), 1)


if __name__ == "__main__":
    unittest.main()
