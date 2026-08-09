# Agent Guide

This file applies to the entire workspace. Use it when developing Engulf itself,
building a wrapping application, authoring a plugin, or reviewing a contribution.

## Start Here

Read the documentation that matches the task before editing code:

- `README.md`: workspace layout, development commands, and release commands.
- `engulf/README.md`: runtime behavior and the complete plugin-authoring guide.
- `engulf-api/README.md`: the versioned plugin contract.

Do not infer the current contract from old terminology or examples. In particular,
`Wrap`, `Wrapper`, and `CallEdits` are not current public APIs. The runtime class is
`Engulf`, and hook capabilities are supplied through `PluginAPI`.

## Workspace Boundaries

This repository contains two independently publishable Python 3.14 distributions:

| Directory | Distribution | Import | Owns |
| --- | --- | --- | --- |
| `engulf-api/` | `engulf-api` | `engulf_api` | Public plugin types and contracts |
| `engulf/` | `engulf` | `engulf` | Discovery, ordering, dispatch, process execution, and shell integration |

Keep the dependency direction one-way:

- `engulf` depends on a compatible `engulf-api` release.
- Plugin wheels depend on `engulf-api`, not on `engulf`, unless they have a separate,
  explicit need for runtime administration APIs.
- `engulf-api` must remain dependency-free and must never import `engulf`.
- Runtime implementations of call-scoped capabilities belong in `engulf`, while the
  abstract contract belongs in `engulf-api`.

Both packages are typed and include `py.typed`. Keep public signatures fully typed and
keep strict MyPy passing.

## Developing A Wrapping Application

A wrapping application constructs one `Engulf` object with the wrapped executable and
a stable application ID:

```python
from engulf import Engulf


application = Engulf("real-command", application_id="my-command")


def main() -> int:
    return application.run()
```

Expose `main` with the wrapping application's normal console-script entry point.

Treat `application_id` as persistent public compatibility metadata. Engulf normalizes
it and derives the installed-plugin group from it. For example, `my-command` maps to
`engulf.plugins.v1.my_command`. Changing the ID silently disconnects every plugin
published for the old group.

Use these application options deliberately:

- `plugin_dir`: optional local development or application-owned plugin directory.
- `discover_installed`: leave enabled for normal installed-plugin discovery; disable
  it only for controlled environments and tests.
- `completion_provider`: reliable wrapped-binary candidates when native shell
  completion cannot provide them.
- `workspace_root_resolver`: optional application policy for mapping a call to its
  canonical persistent-state workspace; the default is the captured CWD.
- `state_home_resolver`: optional application policy for selecting an absolute central
  state home; the default follows XDG and invoking-user sudo semantics.

The constructor validates and registers plugins but does not resolve or execute the
wrapped binary. A bare command is resolved from `PATH` when `run()` executes. An
explicit path is also supported. Never configure the wrapper to execute itself.

Generate Bash or Zsh integration with `engulf-completion`; do not install generated
files into system-owned completion directories from the Python wheel.

## Developing A Plugin

Follow `engulf/README.md#creating-an-installed-plugin` for a complete package tree,
`pyproject.toml`, implementation, build, installation, and discovery check.

### Packaging And Discovery

An installed plugin is a normal wheel with all of the following:

- A compatible dependency such as `engulf-api>=1.0,<2`.
- An entry point in the exact group for the target application, such as
  `engulf.plugins.v1.my_command`.
- An exported `Plugin` instance or zero-argument factory returning one.
- A globally unique, lowercase, dot-qualified `plugin_id`, preferably based on a
  namespace controlled by the publisher.

The entry-point group identifies application compatibility. `plugin_id` identifies
the active plugin. They solve different problems and both are required.

If one plugin needs another plugin wheel, declare both layers:

- Add the required distribution to `[project].dependencies` so installers obtain it.
- Add `PluginDependency` metadata so Engulf verifies that the plugin is active and
  orders it correctly.

Do not rely on package installation alone to imply runtime activation.

### Plugin Metadata

Metadata is read and snapshotted during `Engulf` construction, before registration:

- `plugin_id`: required global identifier.
- `priority`: exact integer, default `50`.
- `plugin_dependencies`: tuple of `PluginDependency`, default empty.
- `context_reads`: `frozenset[str]`, default empty.
- `context_writes`: `frozenset[str]`, default empty.

Keep metadata stable. Do not mutate it from registration or lifecycle hooks.

### Dependencies And Ordering

Engulf builds independent preprocess and postprocess graphs. In a dependency declared
by plugin B for plugin A, each `DependencyPosition` states where A runs relative to B:

- `preprocess=BEFORE`: A preprocesses before B.
- `preprocess=AFTER`: A preprocesses after B.
- `postprocess=BEFORE`: A postprocesses before B.
- `postprocess=AFTER`: A postprocesses after B.
- `None`: no ordering edge for that phase.

The defaults are `BEFORE` for preprocess and `AFTER` for postprocess, producing
middleware order: A before B, binary, B after A. A dependency remains a hard presence
requirement even when both phase positions are `None`.

Among graph nodes currently ready to run, higher priority runs first. Discovery order
breaks equal-priority ties. Do not implement ordering by a simple global priority sort.

Registration, help, preemption precedence, and `Engulf.plugins` use preprocess order.
`Engulf.postprocess_plugins` exposes postprocess order.

### Lifecycle Hooks

Implement only the hooks the plugin needs, but `help()` is required:

```python
from engulf_api import AfterCallEvent, BeforeCallEvent, Plugin, PluginAPI


class ExamplePlugin(Plugin):
    plugin_id = "com.example.my_command.example"

    def help(self) -> str:
        return ""

    def before_call(self, event: BeforeCallEvent, api: PluginAPI) -> None:
        pass

    def after_call(self, event: AfterCallEvent, api: PluginAPI) -> None:
        pass
```

Lifecycle invariants:

- Every before-hook sees the same immutable original `event.wrapper_args`.
- Removals are applied after all successful before-hooks have reviewed the call.
- Argument additions from one plugin are not visible to another plugin.
- Identical added argument groups are coalesced; different groups are retained.
- Editing and preemption methods are available only during preprocessing.
- Context methods are available during either active hook.
- A retained `PluginAPI` object is invalid outside its active hook and is closed after
  the call.
- Structured preemption does not stop remaining before-hooks.
- The first nonzero preemption code in preprocess order wins; zero wins only when no
  plugin supplies a nonzero code.
- A before-hook exception stops preprocessing and skips the binary, but postprocessing
  still receives a framework-failure outcome.
- An after-hook exception stops subsequent postprocessors. Framework hook failures
  return exit code `70`.

Use call context rather than mutable instance attributes for invocation-specific data.
Plugin instances can survive multiple `run()` calls.

### Shared Context

One initially empty context table exists for each `Engulf.run()` and survives through
both lifecycle phases. It is discarded after the call.

- Declare every readable ID in `context_reads`.
- Declare every writable ID in `context_writes`.
- Use lowercase, dot-qualified context IDs owned by an appropriate publisher or
  protocol namespace.
- `get_context(id, default)` returns the default when absent.
- `require_context(id)` raises `MissingContextError` when absent.
- Multiple writers are allowed; later writes overwrite earlier values.
- Only a successful read of an existing value counts as a read.
- At call completion, one `UnusedContextWarning` lists sorted IDs written but never
  read. It does not select a different exit code.

Context read/write declarations do not create dependency graph edges. Declare
`PluginDependency` separately when ordering or hard presence is required.

### Persistent State

Use context for values that live only through one `Engulf.run()`. Use
`api.state(StateScope.WORKSPACE)` for data shared by later operations on the same
logical workspace and `api.state(StateScope.USER)` for user-global plugin data. Do not
invent a combined scope; request each store explicitly.

State API invariants:

- Managed filenames are one validated path component. Prefer `read_*`, `write_*`, and
  `delete` so Engulf retains atomic-write, permission, ownership, and locking behavior.
- `directory` and `path()` exist for interoperability, but direct filesystem access
  bypasses those guarantees.
- `known_workspaces()` is filtered to the calling plugin. It can return stale roots so
  global cleanup remains possible after a workspace is moved or deleted.
- `WorkspaceState.destroy()` is deferred, idempotent, and removes only the caller's
  plugin namespace. The complete workspace record is pruned when no plugin namespaces
  remain.
- Queue cleanup during a hook, then continue to treat state as available for the rest
  of lifecycle dispatch. Cleanup runs after postprocessing, including failure paths.
- State handles are invalid outside the owning plugin's active hook, even though their
  files persist across calls.
- Namespace separation prevents accidental collisions; installed plugins remain
  trusted in-process Python and are not security-sandboxed.

Wrapping applications own workspace identity. Keep resolver behavior and
`application_id` stable once plugins have persisted state. Under recognized sudo,
default state belongs to the invoking user; do not regress this to root-owned state.

### Completion Contributions

Use `register_arguments()` for wrapper options and `register_completions()` for static
or dynamic candidates. Argument declarations affect completion metadata only; they do
not parse, validate, remove, or modify runtime arguments.

Keep the completion coordinator, shell scripts, internal protocol, candidate merging,
and wrapped-binary normalization in Engulf core. Do not turn completion bootstrapping
into an ordinary lifecycle plugin: completion is needed before lifecycle plugins can
service a normal call. A future binary-specific completion adapter should use a
separate backend contract rather than `before_call()` or `after_call()`.

## Contributing To The Framework

Use the existing ownership boundaries:

- `engulf-api/src/engulf_api/plugin.py`: plugin base contract and metadata.
- `engulf-api/src/engulf_api/plugin_api.py`: abstract call capability contract.
- `engulf-api/src/engulf_api/state.py`: persistent state scope and store contracts.
- `engulf-api/src/engulf_api/models.py`: immutable lifecycle values.
- `engulf-api/src/engulf_api/registry.py`: argument and completion contract types.
- `engulf/src/engulf/plugin_loader.py`: discovery, metadata validation, and graph
  ordering.
- `engulf/src/engulf/plugin_api.py`: runtime capability and context implementation.
- `engulf/src/engulf/state.py`: state paths, ownership, managed I/O, catalog locking,
  global workspace discovery, and deferred cleanup implementation.
- `engulf/src/engulf/wrapper.py`: call lifecycle, argument merge, execution, outcomes,
  help, and exit selection.
- `engulf/src/engulf/completion.py`: completion collection and shell bridge.

Prefer narrow changes that preserve these behavioral contracts:

- Validate all plugin metadata before any registration hook runs.
- Snapshot metadata once; do not re-read dynamic attributes during dispatch.
- Keep preprocess and postprocess graph resolution independent.
- Keep argument contributions isolated until merge.
- Emit postprocessing for completed, preempted, signaled, spawn-failed, and
  before-hook-failed calls.
- Preserve direct process execution without invoking a shell.
- Preserve inherited stdin, stdout, and stderr.
- Preserve exit conventions: binary or preemption status normally, `127` not found,
  `126` not executable, `128 + signal` for signals, and `70` for framework failures.
- Attempt every queued workspace cleanup and make any cleanup failure select exit code
  `70` without hiding state from hooks before finalization.

When adding a public API symbol, export it from `engulf_api.__init__` or
`engulf.__init__` as appropriate and add contract tests. Do not expose core runtime
implementation classes from `engulf-api`.

## Tests And Checks

Run commands from the workspace root. The test suites use only local source trees:

```console
PYTHONPATH=engulf-api/src:engulf/src python -m unittest discover -s engulf-api/tests -v
PYTHONPATH=engulf-api/src:engulf/src python -m unittest discover -s engulf/tests -v
ruff check .
ruff format --check .
mypy
```

The project requires Python 3.14. A locally available older interpreter is useful for
quick feedback only; final verification must use Python 3.14. A container can run the
suites without installing the packages:

```console
docker run --rm -v "$PWD":/workspace -w /workspace \
    -e PYTHONPATH=engulf-api/src python:3.14-slim \
    python -m unittest discover -s engulf-api/tests -v
docker run --rm -v "$PWD":/workspace -w /workspace \
    -e PYTHONPATH=engulf-api/src:engulf/src python:3.14-slim \
    python -m unittest discover -s engulf/tests -v
```

Run shell integration tests where Bash and Zsh are installed. A minimal container may
skip Zsh tests, so also run them on a host with Zsh when completion code changes.

Test changes at the owning layer:

- Public contract behavior belongs in `engulf-api/tests`.
- Discovery, dependency graph, context, state, execution, and completion behavior
  belongs in `engulf/tests`.
- Add wheel-level integration coverage when changing package metadata, entry-point
  discovery, or cross-distribution compatibility.
- Cover failure behavior, ordering, and repeated calls, not only the successful path.

## Documentation And Releases

Behavioral changes are incomplete until the relevant README is updated. Keep the
plugin-authoring example copy-pasteable and ensure documented Python and TOML remain
valid. Update all version references together.

For `engulf-api` contract releases:

- Update `engulf-api/pyproject.toml` and `PLUGIN_API_VERSION` together.
- Use semantic versioning. Breaking contract changes require a major version change.
- Change `PLUGIN_API_MAJOR` and entry-point namespaces only for an intentional API
  major transition.
- Update Engulf's dependency range when it begins requiring the new contract.

For runtime releases, update `engulf/pyproject.toml` and its compatible API range.
Build the API before the runtime:

```console
python -m build engulf-api
python -m build engulf
python -m twine check engulf-api/dist/* engulf/dist/*
```

Distribution archives are generated outputs. Never hand-edit them. Rebuild them when
release artifacts are part of the task, and avoid unrelated artifact churn otherwise.
Never upload to a package index unless the user explicitly requests publication.

## Completion Checklist

Before declaring a contribution complete, confirm:

- The change is in the correct distribution and preserves dependency direction.
- Plugin IDs, context IDs, entry-point groups, and version ranges are valid.
- Phase ordering and failure behavior are covered by tests where relevant.
- Both unit-test suites, Ruff, formatting, and strict MyPy pass.
- Python 3.14 has been used for final verification.
- User-facing behavior and plugin contracts are documented.
- Wheels and source distributions were rebuilt and checked when packaging changed.
