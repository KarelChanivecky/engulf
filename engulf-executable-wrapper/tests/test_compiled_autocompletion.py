from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engulf_executable_wrapper import (
    CompiledCompletion,
    CompletionArtifactStore,
    compile_completion,
    completion_environment_fingerprint,
)
from engulf_executable_wrapper_api import (
    ArgumentRegistry,
    CompletionContext,
    CompletionRegistry,
    Match,
    Runtime,
    Shell,
)


class CompiledAutocompletionTests(unittest.TestCase):
    def test_runtime_slot_is_selected_by_declarative_matcher(self) -> None:
        arguments = ArgumentRegistry()
        completions = CompletionRegistry()
        with (
            arguments.owner("com.example.files"),
            completions.owner("com.example.files"),
        ):
            arguments.option(
                "--file",
                takes_value=True,
                value_completer=Runtime(
                    "files",
                    lambda context: ["alpha", "beta"],
                    Match.previous_is("--file"),
                ),
            )
            completions.candidate("status", when=Match.cursor_at(1))

        compiled = compile_completion(
            arguments,
            completions,
            dependencies={"com.example.files": ("com.example.schema",)},
            preprocess_order=("com.example.schema", "com.example.files"),
        )
        context = CompletionContext(
            Shell.BASH, "wrapped", "/bin/echo", ("wrapped", "--file", ""), 2
        )
        self.assertEqual(
            [candidate.value for candidate in compiled.candidates(context)],
            ["alpha", "beta"],
        )
        self.assertEqual(
            compiled.runtime_closure(("com.example.files",)),
            ("com.example.schema", "com.example.files"),
        )

    def test_artifact_fingerprint_invalidates_stale_manifest_atomically(self) -> None:
        arguments = ArgumentRegistry()
        completions = CompletionRegistry()
        completions.candidate("status")
        compiled = compile_completion(arguments, completions)
        fingerprint = completion_environment_fingerprint({"plugins": ["status"]})
        store = CompletionArtifactStore()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "completion.json"
            store.publish(path, compiled.manifest, fingerprint=fingerprint)
            self.assertEqual(
                store.load(path, fingerprint=fingerprint), compiled.manifest
            )
            self.assertIsNone(
                store.load(path, fingerprint=completion_environment_fingerprint({}))
            )
            installed = completion_environment_fingerprint(
                {"plugins": ["status", "new-provider"]}
            )
            removed = completion_environment_fingerprint({"plugins": ["status"]})
            self.assertNotEqual(installed, removed)
            self.assertIsNone(store.load(path, fingerprint=installed))
            self.assertEqual(store.load(path, fingerprint=removed), compiled.manifest)

    def test_static_manifest_evaluates_without_runtime_bindings(self) -> None:
        arguments = ArgumentRegistry()
        completions = CompletionRegistry()
        completions.candidate("status")
        compiled = compile_completion(arguments, completions)
        static_only = CompiledCompletion.from_manifest(compiled.manifest.to_json(), {})
        context = CompletionContext(
            Shell.BASH, "wrapped", "/bin/echo", ("wrapped", "s"), 1
        )
        self.assertEqual(
            [candidate.value for candidate in static_only.candidates(context)],
            ["status"],
        )


if __name__ == "__main__":
    unittest.main()
