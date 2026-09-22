from __future__ import annotations

import unittest

from engulf_executable_wrapper_api import (
    ArgumentRegistry,
    CompletionRegistry,
    Match,
    Runtime,
    build_manifest,
    manifest_from_json,
)


class AutocompletionManifestTests(unittest.TestCase):
    def test_manifest_round_trip_keeps_slots_and_dependency_closure(self) -> None:
        arguments = ArgumentRegistry()
        completions = CompletionRegistry()
        with (
            arguments.owner("com.example.runtime"),
            completions.owner("com.example.runtime"),
        ):
            arguments.option(
                "--item",
                takes_value=True,
                value_completer=Runtime(
                    "items",
                    lambda context: [context.current],
                    Match.previous_is("--item"),
                ),
            )
            completions.candidate("show", when=Match.cursor_at(1))

        manifest = build_manifest(
            arguments,
            completions,
            generation="test-generation",
            dependencies={"com.example.runtime": ("com.example.schema",)},
            preprocess_order=("com.example.schema", "com.example.runtime"),
        )
        restored = manifest_from_json(manifest.to_json())

        self.assertEqual(restored, manifest)
        self.assertEqual(
            manifest.runtime_closure(("com.example.runtime",)),
            ("com.example.schema", "com.example.runtime"),
        )
        self.assertIn("manifest_from_json", manifest.generated_python())
        self.assertNotIn("lambda", manifest.generated_python())

    def test_explicit_runtime_provider_ids_are_unique_per_owner(self) -> None:
        completions = CompletionRegistry()
        with completions.owner("com.example.runtime"):
            completions.provider(Runtime("items", lambda context: []))
            with self.assertRaises(ValueError):
                completions.provider(Runtime("items", lambda context: []))

    def test_option_and_provider_runtime_ids_are_unique_per_owner(self) -> None:
        arguments = ArgumentRegistry()
        completions = CompletionRegistry()
        with arguments.owner("com.example.runtime"):
            arguments.option(
                "--item",
                takes_value=True,
                value_completer=Runtime("items", lambda context: []),
            )
        with completions.owner("com.example.runtime"):
            completions.provider(Runtime("items", lambda context: []))

        with self.assertRaises(ValueError):
            build_manifest(arguments, completions, generation="duplicate")


if __name__ == "__main__":
    unittest.main()
