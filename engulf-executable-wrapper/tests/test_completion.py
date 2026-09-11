from __future__ import annotations

import contextlib
import io
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

from engulf_executable_wrapper import ExecutableWrapperGoal, completion_cli
from engulf_executable_wrapper.completion import (
    collect_candidates,
    normalize_for_binary,
    render_completion_script,
)
from engulf_executable_wrapper_api import (
    CompletionCandidate,
    CompletionContext,
    ExecutableWrapperPlugin,
    Shell,
)

from engulf import Application


class CompletionPlugin(ExecutableWrapperPlugin):
    plugin_id = "tests.completion.primary"

    def help(self, api) -> str:
        del api
        return "completion plugin"

    def register_arguments(self, registry, api) -> None:
        del api
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

    def register_completions(self, registry, api) -> None:
        del api
        registry.candidate("--plugin-command", description="Plugin command")
        registry.provider(lambda context: [CompletionCandidate("--dynamic")])


class CompletionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        elevation = patch("engulf.application.is_process_elevated", return_value=False)
        elevation.start()
        self.addCleanup(elevation.stop)
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.plugin_directory = Path(self.temporary_directory.name)
        with patch(
            "engulf.application.load_directory_plugins",
            return_value=(CompletionPlugin(),),
        ):
            self.goal = ExecutableWrapperGoal(
                "/bin/echo",
                completion_provider=lambda context: ["--base", "--dynamic"],
            )
            self.application = Application(
                "engulf-completion-tests",
                self.goal,
                display_name="engulf-completion-tests",
                vendor="Engulf Tests",
                product="Completion Tests",
                short_product_name="Completion",
                version="0.test",
                plugin_dir=self.plugin_directory,
                discover_installed=False,
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
            self.goal,
            self.context("--"),
            include_binary_provider=True,
        )

        self.assertEqual(
            [candidate.value for candidate in candidates],
            [
                "--base",
                "--dynamic",
                "--engulf-completion-tests-log-level=",
                "--engulf-completion-tests-plugin-log-level=",
                "--plugin=",
                "--visible=",
                "--plugin-command",
            ],
        )

    def test_native_completion_suppresses_explicit_binary_provider(self) -> None:
        candidates = collect_candidates(
            self.goal,
            self.context("--"),
            include_binary_provider=False,
        )

        self.assertNotIn("--base", [candidate.value for candidate in candidates])
        self.assertIn("--dynamic", [candidate.value for candidate in candidates])

    def test_hidden_option_value_suppresses_explicit_binary_provider(self) -> None:
        candidates = collect_candidates(
            self.goal,
            self.context("--plugin=a"),
            include_binary_provider=True,
        )

        self.assertEqual(
            [candidate.value for candidate in candidates], ["--plugin=alpha"]
        )

    def test_completes_separate_and_assigned_option_values(self) -> None:
        separate = collect_candidates(
            self.goal,
            self.context("--plugin", "a"),
            include_binary_provider=False,
        )
        assigned = collect_candidates(
            self.goal,
            self.context("--plugin=b"),
            include_binary_provider=False,
        )

        self.assertEqual([candidate.value for candidate in separate], ["alpha"])
        self.assertEqual([candidate.value for candidate in assigned], ["--plugin=beta"])

    def test_completes_logging_levels_and_plugin_ids(self) -> None:
        global_level = collect_candidates(
            self.goal,
            self.context("--engulf-completion-tests-log-level", "d"),
            include_binary_provider=False,
        )
        plugin_id = collect_candidates(
            self.goal,
            self.context("--engulf-completion-tests-plugin-log-level", "tests.c"),
            include_binary_provider=False,
        )
        plugin_level = collect_candidates(
            self.goal,
            self.context(
                "--engulf-completion-tests-plugin-log-level=tests.completion.primary=i"
            ),
            include_binary_provider=False,
        )

        self.assertEqual([candidate.value for candidate in global_level], ["debug"])
        self.assertEqual(
            [candidate.value for candidate in plugin_id],
            ["tests.completion.primary="],
        )
        self.assertEqual(
            [candidate.value for candidate in plugin_level],
            [
                (
                    "--engulf-completion-tests-plugin-log-level="
                    "tests.completion.primary=info"
                )
            ],
        )

    def test_completes_builtin_install_shell_and_output_path(self) -> None:
        target = self.plugin_directory / "completion-target"
        target.write_text("", encoding="utf-8")
        shell = collect_candidates(
            self.goal,
            self.context("install-completion", "f"),
            include_binary_provider=False,
        )
        output = collect_candidates(
            self.goal,
            self.context(
                "install-completion",
                f"--output={self.plugin_directory}/completion-t",
            ),
            include_binary_provider=False,
        )

        self.assertEqual([candidate.value for candidate in shell], ["fish"])
        self.assertEqual(
            [candidate.value for candidate in output],
            [f"--output={target}"],
        )

    def test_wrapper_logging_options_are_not_completed_after_separator(self) -> None:
        candidates = collect_candidates(
            self.goal,
            self.context("--", "--engulf"),
            include_binary_provider=False,
        )

        self.assertNotIn(
            "--engulf-completion-tests-log-level=",
            [candidate.value for candidate in candidates],
        )

    def test_hides_wrapper_options_from_binary_completion_context(self) -> None:
        words = ("--plugin", "alpha", "sub", "--visible", "yes", "current")

        normalized, cursor = normalize_for_binary(self.goal.arguments, words, 5)

        self.assertEqual(normalized, ("sub", "--visible", "yes", "current"))
        self.assertEqual(cursor, 3)

    def test_hidden_current_value_becomes_empty_binary_word(self) -> None:
        normalized, cursor = normalize_for_binary(
            self.goal.arguments,
            ("--plugin", "alpha"),
            1,
        )

        self.assertEqual(normalized, ("",))
        self.assertEqual(cursor, 0)

    def test_duplicate_option_registration_is_rejected(self) -> None:
        class DuplicatePlugin(ExecutableWrapperPlugin):
            plugin_id = "tests.completion.duplicate"

            def help(self, api) -> str:
                del api
                return ""

            def register_arguments(self, registry, api) -> None:
                del api
                registry.option("--same")
                registry.option("--same")

        with (
            self.assertRaisesRegex(RuntimeError, "already registered"),
            patch(
                "engulf.application.load_directory_plugins",
                return_value=(DuplicatePlugin(),),
            ),
        ):
            Application(
                "engulf-completion-tests",
                ExecutableWrapperGoal("echo"),
                display_name="engulf-completion-tests",
                vendor="Engulf Tests",
                product="Completion Tests",
                short_product_name="Completion",
                version="0.test",
                plugin_dir=self.plugin_directory,
                discover_installed=False,
            )

    def test_completion_sourcing_is_explicit_and_typed(self) -> None:
        self.assertTrue(
            ExecutableWrapperGoal("echo", source_completion=True).source_completion
        )
        with self.assertRaisesRegex(TypeError, "source_completion must be a bool"):
            ExecutableWrapperGoal("echo", source_completion=1)  # type: ignore[arg-type]

    def test_generated_shell_scripts_parse(self) -> None:
        source = "/opt/wrapped command"
        bash_script = render_completion_script(
            Shell.BASH,
            "wrapped",
            "echo",
            completion_source=source,
        )
        zsh_script = render_completion_script(
            Shell.ZSH,
            "wrapped",
            "echo",
            completion_source=source,
        )
        fish_script = render_completion_script(
            Shell.FISH,
            "wrapped",
            "echo",
            completion_source=source,
        )

        bash = subprocess.run(
            ["bash", "-n"],
            input=bash_script,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(bash.returncode, 0, bash.stderr)
        self.assertIn("completion bash", bash_script)
        if shutil.which("zsh"):
            zsh = subprocess.run(
                ["zsh", "-n"],
                input=zsh_script,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(zsh.returncode, 0, zsh.stderr)
        self.assertIn("completion zsh", zsh_script)
        self.assertIn("ENGULF_INTERNAL_SHELL=fish", fish_script)
        self.assertIn("completion fish", fish_script)
        self.assertIn("set -a _engulf_args ''", fish_script)
        self.assertIn("printf '%s\\n'", fish_script)
        self.assertIn("complete -c wrapped", fish_script)


class CompletionCLITestCase(unittest.TestCase):
    @staticmethod
    def invoke_with(result=None, *, side_effect=None):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch(
                "engulf_executable_wrapper.completion_cli.subprocess.run",
                return_value=result,
                side_effect=side_effect,
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            exit_code = completion_cli.main(["bash", "wrapped"])
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_reports_wrapper_launch_failure(self) -> None:
        exit_code, stdout, stderr = self.invoke_with(
            side_effect=FileNotFoundError("missing wrapper")
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("cannot run wrapped: missing wrapper", stderr)

    def test_reports_nonzero_inspection_with_stderr_or_exit_code(self) -> None:
        cases = (
            (23, "inspection failed\n", "inspection failed"),
            (9, "", "exit code 9"),
        )
        for returncode, process_stderr, expected in cases:
            with self.subTest(returncode=returncode, stderr=process_stderr):
                result = subprocess.CompletedProcess(
                    ["wrapped"],
                    returncode,
                    stdout="",
                    stderr=process_stderr,
                )

                exit_code, stdout, stderr = self.invoke_with(result)

                self.assertEqual(exit_code, 1)
                self.assertEqual(stdout, "")
                self.assertIn(f"wrapper inspection failed: {expected}", stderr)

    def test_rejects_malformed_wrapper_descriptions(self) -> None:
        descriptions = (
            "{",
            "{}",
            "[]",
            '{"completion_service": 3}',
            '{"completion_service": ""}',
            '{"completion_service": "bad\\u0000service"}',
            '{"completion_service": "wrapped", "completion_source": 3}',
            '{"completion_service": "wrapped", "completion_source": ""}',
            (
                '{"completion_service": "wrapped", '
                '"completion_source": "bad\\u0000source"}'
            ),
        )
        for description in descriptions:
            with self.subTest(description=description):
                result = subprocess.CompletedProcess(
                    ["wrapped"],
                    0,
                    stdout=description,
                    stderr="",
                )

                exit_code, stdout, stderr = self.invoke_with(result)

                self.assertEqual(exit_code, 1)
                self.assertEqual(stdout, "")
                self.assertIn("invalid wrapper description:", stderr)


class ShellCompletionIntegrationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)
        workspace = Path(__file__).resolve().parents[2]
        self.source_roots = (
            workspace / "engulf-api" / "src",
            workspace / "engulf" / "src",
            workspace / "engulf-executable-wrapper-api" / "src",
            workspace / "engulf-executable-wrapper" / "src",
        )
        self.plugin_directory = self.directory / "plugins"
        self.plugin_directory.mkdir()
        (self.plugin_directory / "example.py").write_text(
            textwrap.dedent(
                """\
                from engulf_executable_wrapper_api import ExecutableWrapperPlugin

                class ExamplePlugin(ExecutableWrapperPlugin):
                    plugin_id = "tests.completion.integration"

                    def help(self, api):
                        return "example"

                    def register_arguments(self, registry, api):
                        registry.option(
                            "--plugin",
                            takes_value=True,
                            value_completer=lambda context: ["alpha", "beta"],
                        )
                        registry.option(
                            "--selector",
                            takes_value=True,
                            value_completer=lambda context: ["default=", "node="],
                            suggest_assignment=False,
                        )

                    def register_completions(self, registry, api):
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
                from unittest.mock import patch
                from engulf import Application
                from engulf_executable_wrapper import ExecutableWrapperGoal

                with patch("engulf.application.is_process_elevated", return_value=False):
                    application = Application(
                        "engulf-shell-integration-tests",
                        ExecutableWrapperGoal(
                            "/bin/echo",
                            completion_provider=lambda context: ["--base"],
                        ),
                        display_name="engulf-shell-tests",
                        vendor="Engulf Tests",
                        product="Shell Completion Tests",
                        short_product_name="Completion",
                        version="0.test",
                        plugin_dir=Path(__file__).with_name("plugins"),
                        discover_installed=False,
                    )
                raise SystemExit(application.run())
                """
            ),
            encoding="utf-8",
        )
        self.wrapper.chmod(0o755)

    def environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        existing = environment.get("PYTHONPATH")
        paths = os.pathsep.join(os.fspath(path) for path in self.source_roots)
        environment["PYTHONPATH"] = (
            paths if not existing else f"{paths}{os.pathsep}{existing}"
        )
        return environment

    @staticmethod
    def function_name(script: str) -> str:
        match = re.search(r"^(_engulf_complete_[0-9a-f]+)\(\)", script, re.MULTILINE)
        if match is None:
            raise AssertionError("generated completion function was not found")
        return match.group(1)

    def native_completion_source(self) -> Path:
        source = self.directory / "real-command"
        source.write_text(
            textwrap.dedent(
                """\
                #!/bin/sh
                test "$1" = completion || exit 2
                case "$2" in
                    bash)
                        printf '%s\n' \\
                            '_real_command_complete() {' \\
                            '    if [[ $COMP_LINE == "real-command " ]]; then' \\
                            '        COMPREPLY=("native-root")' \\
                            '    fi' \\
                            '}' \\
                            'complete -F _real_command_complete real-command'
                        ;;
                    zsh)
                        printf '%s\n' \\
                            'compdef _real_command_complete real-command' \\
                            '_real_command_complete() {' \\
                            '    compadd -- native-root' \\
                            '}'
                        ;;
                    fish)
                        printf '%s\n' \\
                            'complete -c real-command -f -a native-root'
                        ;;
                    *) exit 2 ;;
                esac
                """
            ),
            encoding="utf-8",
        )
        source.chmod(0o755)
        return source

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
            [
                "--base",
                "--engulf-shell-tests-log-level=",
                "--engulf-shell-tests-plugin-log-level=",
                "--plugin=",
                "--selector",
                "--plugin-command",
            ],
        )

    def test_bash_keeps_assignment_candidates_in_the_current_word(self) -> None:
        completion = self.directory / "wrapped-assignment.bash"
        script = render_completion_script(Shell.BASH, str(self.wrapper), "real-command")
        completion.write_text(script, encoding="utf-8")
        function_name = self.function_name(script)
        command = f"""
compopt() {{
    if [[ $1 == -o && $2 == nospace ]]; then
        _engulf_test_nospace=1
    fi
}}
source {shlex.quote(str(completion))}
COMP_WORDS=({shlex.quote(str(self.wrapper))} --engulf-shell-tests-log-l)
COMP_CWORD=1
COMP_LINE={shlex.quote(str(self.wrapper) + " --engulf-shell-tests-log-l")}
COMP_POINT=${{#COMP_LINE}}
{function_name}
printf 'nospace=%s\n' "${{_engulf_test_nospace:-0}}"
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
            ["nospace=1", "--engulf-shell-tests-log-level="],
        )

    def test_bash_separate_value_option_clears_native_nospace(self) -> None:
        completion = self.directory / "wrapped-separate-value.bash"
        script = render_completion_script(Shell.BASH, str(self.wrapper), "real-command")
        completion.write_text(script, encoding="utf-8")
        function_name = self.function_name(script)
        command = f"""
_real_command_complete() {{
    COMPREPLY=()
}}
complete -o nospace -F _real_command_complete real-command
compopt() {{
    if [[ $1 == -o && $2 == nospace ]]; then
        _engulf_test_nospace=1
    elif [[ $1 == +o && $2 == nospace ]]; then
        _engulf_test_nospace=0
    fi
}}
source {shlex.quote(str(completion))}
COMP_WORDS=({shlex.quote(str(self.wrapper))} --sel)
COMP_CWORD=1
COMP_LINE={shlex.quote(str(self.wrapper) + " --sel")}
COMP_POINT=${{#COMP_LINE}}
{function_name}
printf 'nospace=%s\n' "${{_engulf_test_nospace:-0}}"
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
        self.assertEqual(result.stdout.splitlines(), ["nospace=0", "--selector"])

    def test_bash_reassembles_assignment_words_without_bash_completion(self) -> None:
        completion = self.directory / "wrapped-assignment-value.bash"
        script = render_completion_script(Shell.BASH, str(self.wrapper), "real-command")
        completion.write_text(script, encoding="utf-8")
        function_name = self.function_name(script)
        command = f"""
source {shlex.quote(str(completion))}
COMP_WORDS=({shlex.quote(str(self.wrapper))} --plugin = a)
COMP_CWORD=3
COMP_LINE={shlex.quote(str(self.wrapper) + " --plugin=a")}
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
        self.assertEqual(result.stdout.splitlines(), ["alpha"])

    def test_bash_continues_nested_assignment_value_completion(self) -> None:
        completion = self.directory / "wrapped-nested-assignment.bash"
        script = render_completion_script(Shell.BASH, str(self.wrapper), "real-command")
        completion.write_text(script, encoding="utf-8")
        function_name = self.function_name(script)
        command = f"""
compopt() {{
    if [[ $1 == -o && $2 == nospace ]]; then
        _engulf_test_nospace=1
    fi
}}
source {shlex.quote(str(completion))}
COMP_WORDS=({shlex.quote(str(self.wrapper))} --selector =)
COMP_CWORD=2
COMP_LINE={shlex.quote(str(self.wrapper) + " --selector=")}
COMP_POINT=${{#COMP_LINE}}
{function_name}
printf 'nospace=%s\n' "${{_engulf_test_nospace:-0}}"
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
            ["nospace=1", "default=", "node="],
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

    def test_bash_sources_missing_native_completion_and_preserves_empty_word(
        self,
    ) -> None:
        completion = self.directory / "wrapped-native-source.bash"
        script = render_completion_script(
            Shell.BASH,
            str(self.wrapper),
            "real-command",
            completion_source=str(self.native_completion_source()),
        )
        completion.write_text(script, encoding="utf-8")
        function_name = self.function_name(script)
        command = f"""
_minimal() {{
    COMPREPLY=(minimal)
}}
complete -F _minimal real-command
source {shlex.quote(str(completion))}
COMP_WORDS=({shlex.quote(str(self.wrapper))} "")
COMP_CWORD=1
COMP_LINE={shlex.quote(str(self.wrapper) + " ")}
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
        self.assertEqual(result.stdout.splitlines()[0], "native-root")
        self.assertNotIn("minimal", result.stdout.splitlines())
        self.assertNotIn("--base", result.stdout.splitlines())

    def test_bash_minimal_completion_does_not_suppress_binary_provider(self) -> None:
        completion = self.directory / "wrapped-minimal.bash"
        script = render_completion_script(Shell.BASH, str(self.wrapper), "real-command")
        completion.write_text(script, encoding="utf-8")
        function_name = self.function_name(script)
        command = f"""
_minimal() {{
    COMPREPLY=(minimal)
}}
complete -F _minimal real-command
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
        self.assertIn("--base", result.stdout.splitlines())
        self.assertNotIn("minimal", result.stdout.splitlines())

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
            [
                "--base",
                "--engulf-shell-tests-log-level=",
                "--engulf-shell-tests-plugin-log-level=",
                "--plugin=",
                "--selector",
                "--plugin-command",
            ],
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
    def test_zsh_sources_missing_native_completion(self) -> None:
        completion = self.directory / "_wrapped-native-source"
        script = render_completion_script(
            Shell.ZSH,
            str(self.wrapper),
            "real-command",
            completion_source=str(self.native_completion_source()),
        )
        completion.write_text(script, encoding="utf-8")
        function_name = self.function_name(script)
        command = f"""
typeset -A _comps
typeset -ga captured
compdef() {{
    _comps[$2]=$1
}}
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
words=({shlex.quote(str(self.wrapper))} "")
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
        self.assertEqual(result.stdout.splitlines()[0], "native-root")
        self.assertNotIn("--base", result.stdout.splitlines())

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
            [
                "--base",
                "--engulf-shell-tests-log-level=",
                "--engulf-shell-tests-plugin-log-level=",
                "--plugin=",
                "--selector",
                "--plugin-command",
            ],
        )

    def test_completion_generator_inspects_wrapper(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "engulf_executable_wrapper.completion_cli",
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
