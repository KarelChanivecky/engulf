# Engulf Workspace

Engulf is a goal-oriented framework for managed, plugin-based CLI applications.
The core framework owns discovery, lifecycle, diagnostics, state, transactions, and
resource leases. Application-specific behavior lives in a **goal**.

This workspace contains four independently publishable Python 3.14 distributions:

| Directory | Distribution | Responsibility |
| --- | --- | --- |
| `engulf-api/` | `engulf-api` | Stable goal, plugin, lifecycle, and state contracts |
| `engulf/` | `engulf` | Application runtime, discovery, diagnostics, and state implementation |
| `engulf-executable-wrapper-api/` | `engulf-executable-wrapper-api` | Plugin contract for executable wrapping |
| `engulf-executable-wrapper/` | `engulf-executable-wrapper` | Executable goal, process runner, help, and completion |

`engulf` is not itself a binary wrapper. Wrapping an executable is one possible
goal, implemented by `ExecutableWrapperGoal`. A goal can instead implement all of
its work in Python, as shown by [`examples/encryption-app`](examples/encryption-app).

`engulf-api`, `engulf`, and goal API contracts are OS-independent. The core state
runtime selects a POSIX or Windows security and locking backend. The executable
wrapper runtime remains Linux-specific because its process-group, signal-forwarding,
and Bash/Zsh completion behavior is part of that goal.

## Development

Create a Python 3.14 environment. Use that environment's interpreter for the
remaining commands: `.venv/bin/python` on POSIX or
`.venv\Scripts\python.exe` on Windows.

```console
python -m venv --upgrade-deps .venv
python -m pip install --group dev
python -m pip install --no-deps -e ./engulf-api -e ./engulf -e ./engulf-executable-wrapper-api -e ./engulf-executable-wrapper -e ./examples/encryption-app
```

Run every suite from the workspace root:

```console
python -m unittest discover -s engulf-api/tests -v
python -m unittest discover -s engulf-executable-wrapper-api/tests -v
python -m unittest discover -s engulf/tests -v
# Linux only:
python -m unittest discover -s engulf-executable-wrapper/tests -v
python -m ruff check engulf-api engulf engulf-executable-wrapper-api engulf-executable-wrapper examples
python -m ruff format --check engulf-api engulf engulf-executable-wrapper-api engulf-executable-wrapper examples
python -m mypy
```

Build each wheel independently:

```console
python -m build engulf-api
python -m build engulf
python -m build engulf-executable-wrapper-api
python -m build engulf-executable-wrapper
python -m twine check */dist/*
```

See [`engulf/README.md`](engulf/README.md) for application and discovery behavior,
and [`engulf-executable-wrapper-api/README.md`](engulf-executable-wrapper-api/README.md)
for complete executable-wrapper plugin packaging instructions.
