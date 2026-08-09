from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from engulf_api import CompletionCandidate, CompletionContext, Plugin, Shell

from engulf import Engulf
from engulf.completion import (
    collect_candidates,
    normalize_for_binary,
    render_completion_script,
)


class CompletionPlugin(Plugin):
    plugin_id = "tests.completion.primary"

    def help(self) -> str:
        return "completion plugin"

    def register_arguments(self, registry) -> None:
        registry.option(
            "--plugin",
            "-p",
            takes_value=True,
            description="Plugin value",
            value_completer=lambda context: ["alpha", "beta"],
        )
        registry.option(
            "--visible",
            takes_value=True,
            visible_to_binary_completion=True,
        )

    def register_completions(self, registry) -> None:
        registry.candidate("--plugin-command", description="Plugin command")
        registry.provider(lambda context: [CompletionCandidate("--dynamic")])


class CompletionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.plugin_directory = Path(self.temporary_directory.name)
        with patch(
            "engulf.wrapper.load_directory_plugins",
            return_value=(CompletionPlugin(),),
        ):
            self.engulf = Engulf(
                "/bin/echo",
                "engulf-completion-tests",
                plugin_dir=self.plugin_directory,
                discover_installed=False,
                completion_provider=lambda context: ["--base", "--dynamic"],
            )

    def context(self, *words: str, cursor: int | None = None) -> CompletionContext:
        if cursor is None:
            cursor = max(0, len(words) - 1)
        return CompletionContext(
            Shell.BASH,
            "wrapped",
            "/bin/echo",
            tuple(words),
            cursor,
        )

    def test_merges_and_deduplicates_candidates(self) -> None:
        candidates = collect_candidates(
            self.engulf,
            self.context("--"),
            include_binary_provider=True,
        )

        self.assertEqual(
            [candidate.value for candidate in candidates],
            ["--base", "--dynamic", "--plugin=", "--visible=", "--plugin-command"],
        )

    def test_native_completion_suppresses_explicit_binary_provider(self) -> None:
        candidates = collect_candidates(
            self.engulf,
            self.context("--"),
            include_binary_provider=False,
        )

        self.assertNotIn("--base", [candidate.value for candidate in candidates])
        self.assertIn("--dynamic", [candidate.value for candidate in candidates])

    def test_completes_separate_and_assigned_option_values(self) -> None:
        separate = collect_candidates(
            self.engulf,
            self.context("--plugin", "a"),
            include_binary_provider=False,
        )
        assigned = collect_candidates(
            self.engulf,
            self.context("--plugin=b"),
            include_binary_provider=False,
        )

        self.assertEqual([candidate.value for candidate in separate], ["alpha"])
        self.assertEqual([candidate.value for candidate in assigned], ["--plugin=beta"])

    def test_hides_wrapper_options_from_binary_completion_context(self) -> None:
        words = ("--plugin", "alpha", "sub", "--visible", "yes", "current")

        normalized, cursor = normalize_for_binary(self.engulf.arguments, words, 5)

        self.assertEqual(normalized, ("sub", "--visible", "yes", "current"))
        self.assertEqual(cursor, 3)

    def test_hidden_current_value_becomes_empty_binary_word(self) -> None:
        normalized, cursor = normalize_for_binary(
            self.engulf.arguments,
            ("--plugin", "alpha"),
            1,
        )

        self.assertEqual(normalized, ("",))
        self.assertEqual(cursor, 0)

    def test_duplicate_option_registration_is_rejected(self) -> None:
        class DuplicatePlugin(Plugin):
            plugin_id = "tests.completion.duplicate"

            def help(self) -> str:
                return ""

            def register_arguments(self, registry) -> None:
                registry.option("--same")
                registry.option("--same")

        with (
            self.assertRaisesRegex(ValueError, "already registered"),
            patch(
                "engulf.wrapper.load_directory_plugins",
                return_value=(DuplicatePlugin(),),
            ),
        ):
            Engulf(
                "echo",
                "engulf-completion-tests",
                plugin_dir=self.plugin_directory,
                discover_installed=False,
            )

    def test_generated_shell_scripts_parse(self) -> None:
        bash_script = render_completion_script(Shell.BASH, "wrapped", "echo")
        zsh_script = render_completion_script(Shell.ZSH, "wrapped", "echo")

        bash = subprocess.run(
            ["bash", "-n"],
            input=bash_script,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(bash.returncode, 0, bash.stderr)
        if shutil.which("zsh"):
            zsh = subprocess.run(
                ["zsh", "-n"],
                input=zsh_script,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(zsh.returncode, 0, zsh.stderr)


class ShellCompletionIntegrationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)
        self.source_root = Path(__file__).resolve().parents[1] / "src"
        self.plugin_directory = self.directory / "plugins"
        self.plugin_directory.mkdir()
        (self.plugin_directory / "example.py").write_text(
            textwrap.dedent(
                """\
                from engulf_api import Plugin

                class ExamplePlugin(Plugin):
                    plugin_id = "tests.completion.integration"

                    def help(self):
                        return "example"

                    def register_arguments(self, registry):
                        registry.option(
                            "--plugin",
                            takes_value=True,
                            value_completer=lambda context: ["alpha", "beta"],
                        )

                    def register_completions(self, registry):
                        registry.candidate("--plugin-command")

                plugin = ExamplePlugin()
                """
            ),
            encoding="utf-8",
        )
        self.wrapper = self.directory / "wrapped-command"
        self.wrapper.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                from pathlib import Path
                from engulf import Engulf

                engulf = Engulf(
                    "/bin/echo",
                    "engulf-shell-integration-tests",
                    plugin_dir=Path(__file__).with_name("plugins"),
                    discover_installed=False,
                    completion_provider=lambda context: ["--base"],
                )
                raise SystemExit(engulf.run())
                """
            ),
            encoding="utf-8",
        )
        self.wrapper.chmod(0o755)

    def environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        existing = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            str(self.source_root)
            if not existing
            else f"{self.source_root}{os.pathsep}{existing}"
        )
        return environment

    @staticmethod
    def function_name(script: str) -> str:
        match = re.search(r"^(_engulf_complete_[0-9a-f]+)\(\)", script, re.MULTILINE)
        if match is None:
            raise AssertionError("generated completion function was not found")
        return match.group(1)

    def test_bash_explicit_provider_and_plugin_candidates(self) -> None:
        completion = self.directory / "wrapped.bash"
        script = render_completion_script(Shell.BASH, str(self.wrapper), "real-command")
        completion.write_text(script, encoding="utf-8")
        function_name = self.function_name(script)
        command = f"""
source {shlex.quote(str(completion))}
COMP_WORDS=({shlex.quote(str(self.wrapper))} --)
COMP_CWORD=1
COMP_LINE={shlex.quote(str(self.wrapper) + " --")}
COMP_POINT=${{#COMP_LINE}}
{function_name}
printf '%s\n' "${{COMPREPLY[@]}}"
"""

        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", command],
            text=True,
            capture_output=True,
            env=self.environment(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["--base", "--plugin=", "--plugin-command"],
        )

    def test_bash_native_completion_receives_filtered_context(self) -> None:
        completion = self.directory / "wrapped-native.bash"
        script = render_completion_script(Shell.BASH, str(self.wrapper), "real-command")
        completion.write_text(script, encoding="utf-8")
        function_name = self.function_name(script)
        command = f"""
_real_command_complete() {{
    COMPREPLY=("native:${{COMP_WORDS[*]}}:${{COMP_CWORD}}")
}}
complete -F _real_command_complete real-command
source {shlex.quote(str(completion))}
COMP_WORDS=({shlex.quote(str(self.wrapper))} --plugin alpha current)
COMP_CWORD=3
COMP_LINE={shlex.quote(str(self.wrapper) + " --plugin alpha current")}
COMP_POINT=${{#COMP_LINE}}
{function_name}
printf '%s\n' "${{COMPREPLY[@]}}"
"""

        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", command],
            text=True,
            capture_output=True,
            env=self.environment(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["native:real-command current:1"])

    @unittest.skipUnless(shutil.which("zsh"), "zsh is not installed")
    def test_zsh_explicit_provider_and_plugin_candidates(self) -> None:
        completion = self.directory / "_wrapped-command"
        script = render_completion_script(Shell.ZSH, str(self.wrapper), "real-command")
        completion.write_text(script, encoding="utf-8")
        function_name = self.function_name(script)
        command = f"""
typeset -A _comps
typeset -ga captured
compdef() {{ :; }}
compadd() {{
    while (( $# )); do
        if [[ $1 == -- ]]; then
            shift
            break
        fi
        shift
    done
    captured+=("$@")
}}
source {shlex.quote(str(completion))}
words=({shlex.quote(str(self.wrapper))} --)
CURRENT=2
{function_name}
print -rl -- "${{captured[@]}}"
"""

        result = subprocess.run(
            ["zsh", "-f", "-c", command],
            text=True,
            capture_output=True,
            env=self.environment(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["--base", "--plugin=", "--plugin-command"],
        )

    @unittest.skipUnless(shutil.which("zsh"), "zsh is not installed")
    def test_zsh_native_completion_receives_filtered_context(self) -> None:
        completion = self.directory / "_wrapped-native"
        script = render_completion_script(Shell.ZSH, str(self.wrapper), "real-command")
        completion.write_text(script, encoding="utf-8")
        function_name = self.function_name(script)
        command = f"""
typeset -A _comps
typeset -ga captured
compdef() {{ :; }}
compadd() {{
    while (( $# )); do
        if [[ $1 == -- ]]; then
            shift
            break
        fi
        shift
    done
    captured+=("$@")
}}
_real_command_complete() {{
    captured+=("native:${{(j: :)words}}:${{CURRENT}}")
}}
_comps[real-command]=_real_command_complete
source {shlex.quote(str(completion))}
words=({shlex.quote(str(self.wrapper))} --plugin alpha current)
CURRENT=4
{function_name}
print -rl -- "${{captured[@]}}"
"""

        result = subprocess.run(
            ["zsh", "-f", "-c", command],
            text=True,
            capture_output=True,
            env=self.environment(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["native:real-command current:2"])

    @unittest.skipUnless(shutil.which("zsh"), "zsh is not installed")
    def test_zsh_fpath_autoload_completes_on_first_invocation(self) -> None:
        completion = self.directory / "_wrapped-command"
        completion.write_text(
            render_completion_script(Shell.ZSH, "wrapped-command", "real-command"),
            encoding="utf-8",
        )
        command = f"""
fpath=({shlex.quote(str(self.directory))} $fpath)
autoload -Uz compinit
compinit -u -D
typeset -ga captured
compadd() {{
    while (( $# )); do
        if [[ $1 == -- ]]; then
            shift
            break
        fi
        shift
    done
    captured+=("$@")
}}
words=(wrapped-command --)
CURRENT=2
completion_function=${{_comps[wrapped-command]}}
"$completion_function"
print -rl -- "${{captured[@]}}"
"""
        environment = self.environment()
        environment["PATH"] = (
            f"{self.directory}{os.pathsep}{environment.get('PATH', '')}"
        )

        result = subprocess.run(
            ["zsh", "-f", "-c", command],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["--base", "--plugin=", "--plugin-command"],
        )

    def test_completion_generator_inspects_wrapper(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "engulf.completion_cli",
                "bash",
                str(self.wrapper),
            ],
            text=True,
            capture_output=True,
            env=self.environment(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("complete -F", result.stdout)
        self.assertIn("echo", result.stdout)


if __name__ == "__main__":
    unittest.main()
