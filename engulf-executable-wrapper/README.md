# engulf-executable-wrapper

`engulf-executable-wrapper` provides `ExecutableWrapperGoal`, a goal that invokes an
executable while preserving Engulf's managed plugin lifecycle.

This goal runtime targets Linux. Its process-group behavior, forwarded POSIX signal
set, and Bash/Zsh/Fish completion integration are deliberate goal-level platform
requirements; the `engulf` plugin framework itself is OS-independent.

## Wrapping A Command

```python
import sys

from engulf import (
    FRAMEWORK_ERROR_EXIT,
    ApplicationDefinition,
    GoalPrivilegeError,
    PluginPolicy,
)
from engulf_executable_wrapper import ExecutableWrapperGoal


def make_goal() -> ExecutableWrapperGoal:
    return ExecutableWrapperGoal("containerlab")


WRAPPER_APPLICATION = ApplicationDefinition(
    application_id="com.example.containerlab",
    display_name="clab",
    goal_factory=make_goal,
    vendor="Example Corp",
    product="Containerlab Wrapper",
    short_product_name="clab",
    version="1.0.0",
    plugin_policy=PluginPolicy.declared(),
)


def main() -> int:
    try:
        with WRAPPER_APPLICATION.create() as application:
            return application.run()
    except GoalPrivilegeError as error:
        print(f"clab: {error}", file=sys.stderr)
        return FRAMEWORK_ERROR_EXIT
```

Keep the definition in a script-free core module and let each console launcher
create and close a fresh application. Importing the definition then has no discovery,
goal setup, or process side effects.

The executable may be an explicit text path or a command resolved through `PATH`.
All invocation arguments pass through unchanged unless plugin contributions remove,
add, or preempt them.

`ExecutableWrapperGoal` intentionally does not publish Engulf's installed privilege
opt-in metadata, so elevated application construction is rejected before plugins
are loaded or a child is started. An independently implemented goal that opts into
elevated startup must use only trusted plugin packages and an explicit,
administrator-controlled executable path. Engulf currently provides no normal
plugin sandbox or trust grant mechanism.

`Application.invoke()` returns `GoalResult[CallOutcome]`. `Application.run()` returns
the executable, preemption, spawn-failure, or framework exit code.

`ExecutableWrapperGoal(executable, *, completion_provider=None,
source_completion=False)` accepts a nonempty text command or path. A bare command is
resolved through `PATH` for each invocation; a path is expanded for `~` and made
absolute. The optional provider supplies fallback completion for the wrapped command
when the shell has no native completion. `source_completion=True` additionally lets
the generated shell integration invoke the executable as `completion <shell>` and
source its output when no real native completion is registered. The `executable`,
`completion_provider`, and `source_completion` properties expose that configuration;
`arguments` and `completions` expose the setup-owned metadata registries used by
completion integration.

Completion sourcing is an explicit application opt-in because the generated output
executes in the interactive shell. Enable it only for a trusted executable with the
documented `completion bash|zsh|fish` contract.

The goal's `contract`, `setup()`, and `achieve()` implement the managed `Goal`
lifecycle and are called by `Application`; application code should not invoke them
directly.

## Behavior

For each normal invocation, the goal:

1. consumes registered environment-backed wrapper options and overlays their values
   before outer plugin callbacks;
2. dispatches every plugin's side-effect-free `analyze_call`;
3. validates and merges all argument contributions;
4. resolves preemption before external preparation;
5. dispatches `prepare_call` only when execution remains viable;
6. unwinds preparation with `prepare_failed` if a preparer raises, then propagates
   the original error;
7. executes the child while forwarding wrapper signals;
8. dispatches `after_call` in postprocessing order;
9. returns a typed outcome to outer `after_goal` middleware.

The child shares the wrapper's existing process group. This preserves controlling
terminal and shell job-control behavior. While the child is alive, temporary handlers
forward SIGHUP, SIGINT, SIGQUIT, SIGTERM, SIGUSR1, SIGUSR2, and SIGWINCH, then restore
the wrapper's previous handlers. Child termination by signal maps to `128 + signal`.

Spawn failures use conventional exits: 127 when not found and 126 when the executable
cannot be invoked. Directly resolving the executable to the wrapper itself is
rejected.

Execution is shell-free. The child inherits the wrapper's standard streams,
environment, current directory, controlling terminal, and process group. The runtime
does not capture child output or create a new session. Direct recursion is reported
as a spawn failure with exit 126.

The wrapper maps call outcomes to framework results as follows:

| Call outcome | `GoalResultStatus` | Exit |
| --- | --- | ---: |
| Child exited, including nonzero | `COMPLETED` | Child exit |
| Plugin preemption | `REJECTED` | Selected preemption exit |
| Not found | `FAILED` | `127` |
| Permission, recursion, or other spawn error | `FAILED` | `126` |
| Child signal | `FAILED` | `min(255, 128 + signal)` |
| Lifecycle, phase, validation, or cleanup error | `FRAMEWORK_FAILED` | `70` |

`after_call` runs for preemption, spawn failure, child signal, and normal child exit.
It never runs when no call was attempted.

If preparation fails, it stops, the executable never starts, and the goal dispatches
`PreparationFailedEvent` to exactly the plugins whose own `prepare_call` already
returned, in reverse preparation order. The plugin that raised is not called and must
unwind its own partial work; plugins that never prepared are not called. That phase
isolates failures, so a raising `prepare_failed` is reported and the remaining
plugins still unwind.

Preparation is dispatched one plugin at a time so the goal tracks progress itself
rather than reading it from the failure. Anything that ends the phase therefore
unwinds the same plugins: an ordinary exception continues to outer lifecycle handling
as a `FRAMEWORK_FAILED` result with exit 70, while `KeyboardInterrupt` and
`SystemExit` unwind first and then propagate unchanged, preserving normal Ctrl-C and
exit behavior.

Analysis errors occur before external work is allowed, so they unwind nothing.

## Help

When an exact `--help` argument is present, the goal invokes the executable with the
original arguments. Plugin edits and preemption are ignored, and preparation is
skipped. After the executable's output, Engulf appends logging options and nonempty
plugin help blocks collected during setup. Each block appears in its own visibly
separated section headed by the plugin's stable ID. Values such as `--help=topic`
remain normal arguments.

Analyzers still run in help mode and see `CallMode.HELP`, so they must remain
side-effect free. `after_call` also runs with the help outcome before the wrapper
appends its own sections. The child exit remains the invocation exit.

## Completion

The goal mirrors existing Bash, Zsh, and Fish completion for the wrapped executable and
merges plugin candidates. Wrapper-only options are removed from the completion
context sent to native executable completion.

Install completion through the wrapper command itself:

```console
my-wrapper install-completion bash
my-wrapper install-completion zsh
my-wrapper install-completion fish
```

With no shell argument, the command detects Bash, Zsh, or Fish from `SHELL`. Default
destinations honor XDG directories:

| Shell | Default path |
| --- | --- |
| Bash | `$XDG_DATA_HOME/bash-completion/completions/my-wrapper` |
| Zsh | `$XDG_DATA_HOME/zsh/site-functions/_my-wrapper` |
| Fish | `$XDG_CONFIG_HOME/fish/completions/my-wrapper.fish` |

Use `--output PATH` for an explicit location. The installer creates parent
directories and atomically replaces a prior Engulf-generated regular file. It
refuses symlinks, non-files, and unrecognized existing content. For Zsh, ensure
the reported directory is on `fpath` before `compinit`.

The standalone generator remains available for packaging or inspection workflows:

```console
engulf-completion bash my-wrapper > ~/.local/share/bash-completion/completions/my-wrapper
engulf-completion zsh my-wrapper > ~/.local/share/zsh/site-functions/_my-wrapper
engulf-completion fish my-wrapper > ~/.config/fish/completions/my-wrapper.fish

# Or let the generator write the file:
engulf-completion bash my-wrapper \
  --output ~/.local/share/bash-completion/completions/my-wrapper
```

The generator invokes the wrapper through a private environment protocol to discover
the wrapped executable and whether the application opted into completion sourcing.
Existing native completion is preferred. When sourcing is enabled and no native
completion is registered, the integration sources `<executable> completion <shell>`
once and then rechecks the shell's completion registry. Bash's generic `_minimal`
fallback is not treated as native completion. For Zsh, place the generated wrapper
file on `fpath` before `compinit` or source it after `compinit`.

Application-defined binary providers are used only when no native completion was
found. Static and dynamic plugin candidates are merged and deduplicated.

The generator executes the wrapper once to discover its configured executable and
returns 1 when the wrapper cannot launch, reports a nonzero inspection exit, or
returns an invalid description. Its `wrapper` argument may be a command or path.

Applications can render a script without running the inspection CLI:

```python
from engulf_executable_wrapper import render_completion_script
from engulf_executable_wrapper_api import Shell

script = render_completion_script(
    Shell.BASH,
    wrapper_command="my-wrapper",
    binary_service="wrapped-command",
    completion_source="/usr/bin/wrapped-command",
)
```

`binary_service` is the native completion service name, normally the basename of
the configured executable. `completion_source` is optional and names the trusted
executable whose `completion <shell>` output may be sourced. All supplied names must
be nonempty and NUL-free. The
`ENGULF_INTERNAL_*` environment protocol embedded in generated scripts is private;
applications and plugins must not call or extend it.

Wrapper-only registered options and their values are hidden from native completion
before `--` unless their `OptionSpec` explicitly sets
`visible_to_binary_completion=True`. Options after `--` remain native arguments.
Native and fallback binary completion are skipped while the cursor is inside a
hidden wrapper option or its value. The Bash integration reassembles assignments
split by `COMP_WORDBREAKS` and keeps candidates ending in `=` or a directory `/`
in the current word so chained value completion can continue.
When native completion exists, it supplies binary candidates and suppresses the
application's fallback binary provider; plugin option, static, and dynamic
candidates are still merged.

## Writing Plugins

Depend on `engulf-executable-wrapper-api`, not this runtime package. The complete
plugin class, immutable contribution model, lifecycle rules, and reusable wheel
metadata are documented in
[`engulf-executable-wrapper-api/README.md`](../engulf-executable-wrapper-api/README.md).

## Public Import Surface

`engulf_executable_wrapper` also exports `CompiledCompletion`,
`CompletionArtifactStore`, `compile_completion`, and
`completion_environment_fingerprint`. These helpers evaluate a compiled manifest,
publish it atomically, and reject it when installed metadata has changed. It still
exports `ExecutableWrapperGoal` and `render_completion_script`. Import `Shell`,
events, outcomes, contribution types, registries, and the plugin base from
`engulf_executable_wrapper_api`. Import `ApplicationDefinition`, policies, and
runtime configuration from `engulf`.
