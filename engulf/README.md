# Engulf

Engulf is a Python 3.14 framework for building transparent, plugin-driven wrappers
around existing command-line programs. Normal stdin, stdout, and stderr are inherited
by the wrapped process, and arguments pass through unchanged unless plugins explicitly
remove or add them.

The runtime depends on the separately versioned `engulf-api` distribution. Plugin
implementations import `engulf_api`, not `engulf`.

## Wrapping Application

The application supplies the wrapped binary and its stable distribution name:

```python
from engulf import Engulf


engulf = Engulf("real-command", application_id="my-command")


def main() -> int:
    return engulf.run()
```

The consuming application exposes `main` as its console entry point:

```toml
[project.scripts]
my-command = "my_package.cli:main"
```

An explicit binary path can be supplied instead of a command name. Command names are
resolved from `PATH` immediately before execution, and Engulf never invokes a shell.

## Creating An Installed Plugin

An installed plugin is a normal wheel that depends on `engulf-api` and publishes an
entry point for one wrapping application. It should not import from `engulf`; runtime
types used by plugins belong to `engulf_api`.

The following example creates an audit plugin for an application constructed with:

```python
Engulf("real-command", application_id="my-command")
```

### 1. Choose The Identifiers

The application ID determines the entry-point group. Engulf normalizes runs of `-`,
`_`, and `.` to `-`, lowercases the result, and uses `_` in the group suffix:

| Application ID | Normalized ID | Entry-point group |
| --- | --- | --- |
| `my-command` | `my-command` | `engulf.plugins.v1.my_command` |
| `Acme.CLI` | `acme-cli` | `engulf.plugins.v1.acme_cli` |

The `v1` component is `PLUGIN_API_MAJOR`, not the version of the wrapping application
or plugin. A plugin is considered for discovery only when its group exactly matches
the wrapping application's group.

Each plugin also needs a globally unique `plugin_id`. Use a lowercase, dot-qualified
name controlled by the plugin publisher, such as
`com.example.my_command.audit`. Entry-point names such as `audit` are only package
labels and do not replace `plugin_id`.

### 2. Create The Package

Create this source layout:

```text
my-command-audit-plugin/
|-- pyproject.toml
`-- src/
    `-- my_command_audit/
        |-- __init__.py
        `-- py.typed
```

Use this complete `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
name = "my-command-audit-plugin"
version = "0.1.0"
description = "Audit logging for my-command"
requires-python = ">=3.14"
license = "MIT"
dependencies = [
    "engulf-api>=1.2,<2",
    "my-command>=2,<3",
]

[project.entry-points."engulf.plugins.v1.my_command"]
audit = "my_command_audit:plugin"

[tool.hatch.build.targets.wheel]
packages = ["src/my_command_audit"]
```

Depending on the wrapping application is recommended when the plugin requires a
particular application version. Depending directly on `engulf-api` makes the plugin's
contract compatibility explicit. The upper bound prevents installation with a future
breaking API major.

The entry-point value has the form `importable_module:exported_object`. The exported
object may be a `Plugin` instance or a zero-argument callable that returns one.

### 3. Implement The Plugin

Put the following in `src/my_command_audit/__init__.py`:

```python
from pathlib import Path

from engulf_api import (
    AfterCallEvent,
    ArgumentRegistry,
    BeforeCallEvent,
    Plugin,
    PluginAPI,
)

_AUDIT_PATH = "com.example.my_command.audit.path"


class AuditPlugin(Plugin):
    plugin_id = "com.example.my_command.audit"
    priority = 50
    context_reads = frozenset({_AUDIT_PATH})
    context_writes = frozenset({_AUDIT_PATH})

    def help(self) -> str:
        return "  --audit-log PATH   Append the wrapped command's exit code"

    def register_arguments(self, registry: ArgumentRegistry) -> None:
        registry.option(
            "--audit-log",
            takes_value=True,
            metavar="PATH",
            description="Append the wrapped command's exit code",
        )

    def before_call(self, event: BeforeCallEvent, api: PluginAPI) -> None:
        index = 0
        while index < len(event.wrapper_args):
            argument = event.wrapper_args[index]
            if argument.startswith("--audit-log="):
                path = argument.partition("=")[2]
                if not path:
                    api.preempt(2)
                    return
                api.remove(index)
                api.set_context(_AUDIT_PATH, path)
            elif argument == "--audit-log":
                if index + 1 >= len(event.wrapper_args):
                    api.preempt(2)
                    return
                api.remove_range(index, index + 2)
                api.set_context(_AUDIT_PATH, event.wrapper_args[index + 1])
                index += 1
            index += 1

    def after_call(self, event: AfterCallEvent, api: PluginAPI) -> None:
        path = api.get_context(_AUDIT_PATH)
        if isinstance(path, str):
            with Path(path).open("a", encoding="utf-8") as stream:
                stream.write(f"{event.outcome.exit_code}\n")


plugin = AuditPlugin()
```

Create an empty `src/my_command_audit/py.typed` file so type checkers recognize the
installed package as typed.

This plugin declares `--audit-log` for completion, removes it before the wrapped
binary runs, stores its value in call-scoped context, and reads that value in
postprocessing. `api.preempt(2)` handles a missing value without launching the binary.
Argument removal is deferred, so every plugin still sees the original
`event.wrapper_args` tuple.

### 4. Build And Install It

From the plugin project directory, create an isolated environment and build both the
wheel and source distribution:

```console
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip build
python -m build
```

The build produces files similar to:

```text
dist/my_command_audit_plugin-0.1.0-py3-none-any.whl
dist/my_command_audit_plugin-0.1.0.tar.gz
```

Install the wrapping application first if it is not already installed, then install
the wheel:

```console
python -m pip install my-command
python -m pip install --force-reinstall \
    dist/my_command_audit_plugin-0.1.0-py3-none-any.whl
```

Do not use `--no-deps` for a production installation: package dependencies are how
the required API, wrapping application, and any dependent plugin wheels are installed.

### 5. Verify Discovery

Run this in the same environment. Constructing `Engulf` discovers and validates
plugins but does not execute the wrapped binary:

```console
python - <<'PY'
from engulf import Engulf

application = Engulf("real-command", application_id="my-command")
print(application.plugin_entry_point_group)
print([plugin.plugin_id for plugin in application.plugins])
PY
```

The output must include:

```text
engulf.plugins.v1.my_command
['com.example.my_command.audit']
```

Other plugins installed for the same application may also appear in the list. Run
`my-command --help` to verify that the wrapped binary's help is followed by the
plugin's `--audit-log` help block.

If the plugin is absent, check all of these values:

- The wrapper's `application_id` and the entry-point group suffix match after
  normalization.
- The entry point uses the current API major, currently `v1`.
- The entry-point module and exported object are importable in the wrapper's Python
  environment.
- The exported instance or factory result subclasses `engulf_api.Plugin`.
- `plugin_id` is lowercase, dot-qualified, and unique among active plugins.
- The installed `engulf-api` version satisfies both the plugin and runtime ranges.

Installed plugins are discovered in deterministic distribution-name,
entry-point-name, and object-reference order before dependency and priority ordering.
Discovery can be disabled with `discover_installed=False`.

Entry points are declarations, not a security boundary. Installing and activating a
plugin permits it to execute Python code in the wrapping application's process.

### Plugin Contract Reference

| Member | Requirement | Purpose |
| --- | --- | --- |
| `plugin_id` | Required | Globally identifies the active plugin. |
| `help()` | Required | Returns the plugin-specific help block as a string. |
| `priority` | Optional, default `50` | Breaks ties among dependency-ready plugins. |
| `plugin_dependencies` | Optional, default `()` | Requires and orders other active plugins. |
| `context_reads` | Optional, default empty | Declares context IDs the plugin may read. |
| `context_writes` | Optional, default empty | Declares context IDs the plugin may write. |
| `register_arguments()` | Optional | Declares wrapper options used by completion. |
| `register_completions()` | Optional | Adds static or dynamic completion candidates. |
| `before_call(event, api)` | Optional | Inspects original arguments, edits the effective call, shares context, or preempts. |
| `after_call(event, api)` | Optional | Observes the outcome and accesses shared context. |

## Local Plugins

An application may additionally point to a local plugin directory:

```python
from pathlib import Path

from engulf import Engulf


engulf = Engulf(
    "real-command",
    application_id="my-command",
    plugin_dir=Path(__file__).with_name("plugins"),
)
```

Each non-private, immediate `*.py` file must export `plugin` using the same instance or
factory contract. Private `_*.py` modules may be imported as helpers. Local files are
discovered in lexical filename order before installed plugins. The directory is
optional but must exist when supplied.

Import errors, missing or invalid exports, duplicate installed entry points, and
factory failures raise `PluginLoadError` during `Engulf` construction. Invalid plugin
metadata, duplicate plugin IDs, missing hard dependencies, and dependency cycles raise
`PluginDependencyError` before registration starts.

## Plugin Call Model

Every plugin must define a globally unique, lowercase, dot-qualified `plugin_id`, such
as `com.example.my_command.audit`. After discovery, Engulf snapshots and validates all
plugin metadata, then computes independent preprocess and postprocess topological
orders. Among graph nodes currently ready to run, higher integer `priority` runs
first; the neutral default is `50`, and ties preserve discovery order.

Argument and completion registration, help output, preemption precedence, and the
public `Engulf.plugins` tuple use preprocess order. `Engulf.postprocess_plugins`
exposes postprocess order. Plugins cannot inspect argument edits made by another
plugin. Each before-hook receives an immutable `BeforeCallEvent` and a private,
call-scoped `PluginAPI` view.

- `remove(index)` and `remove_range(start, stop)` refer to indexes in the original
  wrapper argument tuple. All removals are unioned after every plugin has run.
- `add(*args, placement=...)` records one atomic group. Exact duplicate groups are
  emitted once, and the first request chooses their placement.
- Placements are `PREPEND`, `BEFORE_SEPARATOR` (the default), and `APPEND`.
- `preempt(code)` skips the binary. The first nonzero code wins; a zero code is used
  only when no plugin supplied a nonzero code.

All before-hooks continue after a structured preemption. Every plugin then receives an
`AfterCallEvent` describing execution, preemption, a signal, or a spawn failure.
After-hooks are observers and cannot change the selected exit code.

## Dependencies And Shared Context

A plugin wheel uses normal package dependencies to install another plugin wheel, and
uses `PluginDependency` to require that plugin to be active and constrain lifecycle
order:

```toml
[project]
dependencies = [
    "engulf-api>=1.2,<2",
    "my-command-identity-plugin>=1,<2",
]
```

```python
from engulf_api import DependencyPosition, Plugin, PluginDependency


class AuditPlugin(Plugin):
    plugin_id = "com.example.my_command.audit"
    plugin_dependencies = (
        PluginDependency(
            "com.example.my_command.identity",
            preprocess=DependencyPosition.BEFORE,
            postprocess=DependencyPosition.AFTER,
        ),
    )

    def help(self) -> str:
        return ""
```

`BEFORE` and `AFTER` describe the dependency's position relative to the declaring
plugin. The defaults shown above produce middleware order: identity before audit in
preprocessing, then audit before identity in postprocessing. Set either phase to
`None` to omit only that ordering constraint. Hard presence is still checked. Each
phase has its own cycle validation.

One initially empty context table lives for the entire `Engulf.run()` call. Plugins
declare context capabilities and use their scoped API during either hook:

```python
class IdentityPlugin(Plugin):
    plugin_id = "com.example.my_command.identity"
    context_writes = frozenset({"com.example.my_command.principal"})

    def help(self) -> str:
        return ""

    def before_call(self, event, api) -> None:
        api.set_context("com.example.my_command.principal", "alice")


class AuditPlugin(Plugin):
    plugin_id = "com.example.my_command.audit"
    context_reads = frozenset({"com.example.my_command.principal"})

    def help(self) -> str:
        return ""

    def after_call(self, event, api) -> None:
        principal = api.require_context("com.example.my_command.principal")
```

Reads and writes outside a plugin's declarations fail. Multiple writers are allowed;
later writes overwrite earlier values. `get_context(id, default)` returns the default
when absent, while `require_context(id)` raises `MissingContextError`. Only reading an
existing value counts as a read. At call completion, Engulf emits one filterable
`UnusedContextWarning` containing the sorted IDs written but never read; it does not
change the exit code. The table is discarded after each call.

Any exact `--help` argument enters help mode. Plugin hooks still receive events, but
their edits and preemptions are ignored. The original arguments are passed to the
binary, followed by each plugin's nonempty `help()` block.

Plugin hook exceptions are programming failures. A before-hook exception stops the
before phase and skips execution; an after-hook exception stops the after phase. Engulf
returns exit code 70 for either case. Missing and non-executable binaries return 127 and
126 respectively, and signal exits are normalized to `128 + signal`.

## Completion Metadata

Argument declarations are used only for completion. They do not parse, validate,
remove, or otherwise change runtime arguments.

```python
from engulf_api import CompletionCandidate, Plugin


class EnvironmentPlugin(Plugin):
    plugin_id = "com.example.my_command.environment"

    def help(self) -> str:
        return "  --environment NAME   Select an environment"

    def register_arguments(self, registry) -> None:
        registry.option(
            "--environment",
            takes_value=True,
            metavar="NAME",
            description="Select an environment",
            value_completer=lambda context: [
                CompletionCandidate("development"),
                CompletionCandidate("production"),
            ],
        )


plugin = EnvironmentPlugin
```

Plugins may also use `register_completions()` to add literal candidates or dynamic
providers. An `Engulf`-level `completion_provider` supplies reliable wrapped-binary
candidates when no compatible native shell completion is loaded.

## Bash And Zsh

Install the wrapping application first, then generate its completion script:

```console
engulf-completion bash my-command > my-command.bash
engulf-completion zsh my-command > _my-command
```

For Bash, source the wrapped binary's completion first and then source the generated
file. For Zsh, put `_my-command` in a directory on `fpath` before running `compinit`, or
source it after `compinit`.

System packages can place generated files in:

- `/usr/share/bash-completion/completions/my-command`
- `/usr/share/zsh/site-functions/_my-command`

The wheel intentionally does not write to those system-owned directories.
