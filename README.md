# Engulf Workspace

Engulf is a goal-oriented framework for managed, plugin-based CLI applications.
The core framework owns discovery, lifecycle, diagnostics, state, transactions, and
resource leases. Application-specific behavior lives in a **goal**.

This workspace contains five independently publishable Python 3.14 distributions:

| Directory | Distribution | Responsibility |
| --- | --- | --- |
| `engulf-api/` | `engulf-api` | Stable goal, plugin, lifecycle, and state contracts |
| `engulf/` | `engulf` | Application runtime, discovery, diagnostics, and state implementation |
| `engulf-executable-wrapper-api/` | `engulf-executable-wrapper-api` | Plugin contract for executable wrapping |
| `engulf-executable-wrapper/` | `engulf-executable-wrapper` | Executable goal, process runner, help, and completion |
| `plugins/engulf-plugin-list/` | `engulf-plugin-list` | Isolated executable-wrapper plugin inventory diagnostic |

`engulf` is not itself a binary wrapper. Wrapping an executable is one possible
goal, implemented by `ExecutableWrapperGoal`. A goal can instead implement all of
its work in Python, as shown by the reusable
[`examples/encryption-core`](examples/encryption-core) package and its thin
[`examples/encryption-app`](examples/encryption-app) launcher.

`engulf-api`, `engulf`, and goal API contracts are OS-independent. The core state
runtime selects a POSIX or Windows security and locking backend. The executable
wrapper runtime remains Linux-specific because its process-group, signal-forwarding,
and Bash/Zsh completion behavior is part of that goal.

## Execution Boundaries

Engulf imports and executes every selected normal goal plugin in the application
process with that process's full operating-system authority. `PluginPolicy` is an
activation policy, `ElevationRequirement` is a compatibility declaration, and
managed state paths are namespace conveniences; none of them is a trust boundary or
sandbox. An elevated application therefore elevates every selected plugin.

Applications must select only trusted code when they run elevated. Keep application
code, its Python environment, and `plugin_dir` outside locations writable by less
privileged users. A future execution backend may isolate compatible plugins, so the
public contract exposes immutable plugin metadata and source records and routes
callbacks through stable phase IDs. No current plugin should infer that isolation is
already present.

Diagnostic extensions are a separate, automatically discovered extension kind.
Their targets are never imported by the application process. On Linux, an exact
reserved trigger runs each matching target in its own bounded Bubblewrap sandbox,
using a length-limited JSON protocol. The sandbox has no workspace, home, host
temporary directory, or network view. If that isolation cannot be established,
Engulf leaves diagnostics disabled and safely rejects their declared triggers.
This boundary does not make normal goal plugins safer: those remain trusted,
in-process code with the application's full authority.

## Development

Create a Python 3.14 environment. Use that environment's interpreter for the
remaining commands: `.venv/bin/python` on POSIX or
`.venv\Scripts\python.exe` on Windows.

```console
python -m venv --upgrade-deps .venv
python -m pip install --group dev
python -m pip install --no-deps -e ./engulf-api -e ./engulf -e ./engulf-executable-wrapper-api -e ./engulf-executable-wrapper -e ./plugins/engulf-plugin-list -e ./examples/encryption-core -e ./examples/encryption-app
```

Run every suite from the workspace root:

```console
python -m unittest discover -s engulf-api/tests -v
python -m unittest discover -s engulf-executable-wrapper-api/tests -v
python -m unittest discover -s engulf/tests -v
# Linux only:
python -m unittest discover -s engulf-executable-wrapper/tests -v
python -m ruff check engulf-api engulf engulf-executable-wrapper-api engulf-executable-wrapper plugins examples
python -m ruff format --check engulf-api engulf engulf-executable-wrapper-api engulf-executable-wrapper plugins examples
python -m mypy
```

Build all five wheels and source distributions, then validate their package
metadata with Twine. The script creates `.venv` and installs the development
dependencies when the workspace environment does not exist:

```console
./build.sh
```

## Publishing

Publish all five distributions to TestPyPI by default. Twine reads credentials from
its standard configuration or the `TWINE_USERNAME` and `TWINE_PASSWORD` environment
variables:

```console
./publish.sh
```

Publishing to the production PyPI index requires an explicit repository override:

```console
./publish.sh --repository pypi
```

See [`engulf/README.md`](engulf/README.md) for application and discovery behavior,
and [`engulf-executable-wrapper-api/README.md`](engulf-executable-wrapper-api/README.md)
for complete executable-wrapper plugin packaging instructions.
