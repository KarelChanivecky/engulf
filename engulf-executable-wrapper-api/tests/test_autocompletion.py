from __future__ import annotations

import unittest

from engulf_executable_wrapper_api import (
    ArgumentRegistry,
    CompletionContext,
    CompletionRegistry,
    Match,
    Runtime,
    Shell,
    build_manifest,
    manifest_from_json,
)


class AutocompletionManifestTests(unittest.TestCase):
    def test_match_factories_and_boolean_composition(self) -> None:
        context = CompletionContext(
            Shell.BASH,
            "wrapped",
            "/bin/echo",
            ("command", "--json", "dev"),
            2,
        )

        self.assertTrue(Match.always().matches(context))
        self.assertTrue(Match.words_prefix(("command", "--json")).matches(context))
        self.assertFalse(Match.words_prefix(("other",)).matches(context))
        self.assertTrue(Match.current_prefix("d").matches(context))
        self.assertFalse(Match.current_prefix("prod").matches(context))
        self.assertTrue(Match.any_prior_word(("--json",)).matches(context))
        self.assertFalse(Match.any_prior_word(("--quiet",)).matches(context))

        combined = Match.words_prefix(("command",)) & Match.cursor_at(2)
        self.assertTrue(combined.matches(context))
        self.assertTrue(
            (Match.current_prefix("prod") | Match.current_prefix("d")).matches(context)
        )
        self.assertTrue((~Match.previous_is("--quiet")).matches(context))

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
            postprocess_order=("com.example.runtime", "com.example.schema"),
        )
        restored = manifest_from_json(manifest.to_json())

        self.assertEqual(restored, manifest)
        self.assertEqual(
            manifest.runtime_closure(("com.example.runtime",)),
            ("com.example.schema", "com.example.runtime"),
        )
        self.assertEqual(
            manifest.postprocess_order,
            ("com.example.runtime", "com.example.schema"),
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

    def test_registrations_retain_the_declaring_owner(self) -> None:
        arguments = ArgumentRegistry()
        completions = CompletionRegistry()
        with (
            arguments.owner("com.example.owner"),
            completions.owner("com.example.owner"),
        ):
            arguments.option("--owned")
            completions.candidate("owned")
            completions.provider(Runtime("provider", lambda context: []))

        self.assertEqual(arguments.options[0].owner_id, "com.example.owner")
        self.assertEqual(
            completions.candidate_records[0].owner_id,
            "com.example.owner",
        )
        self.assertEqual(
            completions.provider_records[0].owner_id,
            "com.example.owner",
        )


if __name__ == "__main__":
    unittest.main()
