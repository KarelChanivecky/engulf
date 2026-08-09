# Engulf Workspace

This repository contains two independently publishable Python 3.14 distributions:

| Directory | Distribution | Import package | Responsibility |
| --- | --- | --- | --- |
| `engulf-api/` | `engulf-api` | `engulf_api` | Stable, dependency-free plugin contract |
| `engulf/` | `engulf` | `engulf` | Plugin discovery, process execution, and shell integration |

`engulf` depends on `engulf-api>=1.2,<2`. Installed plugins depend directly on
`engulf-api`, so plugin compatibility follows the API distribution's semantic
version without coupling plugins to the runtime implementation.

## Development

Run both suites from the workspace root:

```console
PYTHONPATH=engulf-api/src:engulf/src python -m unittest discover -s engulf-api/tests -v
PYTHONPATH=engulf-api/src:engulf/src python -m unittest discover -s engulf/tests -v
ruff check engulf-api/src engulf-api/tests engulf/src engulf/tests
ruff format --check engulf-api/src engulf-api/tests engulf/src engulf/tests
mypy
```

Build each distribution independently:

```console
python -m build engulf-api
python -m build engulf
python -m twine check engulf-api/dist/* engulf/dist/*
```

See [`engulf-api/README.md`](engulf-api/README.md) for the versioned contract and
[`engulf/README.md`](engulf/README.md#creating-an-installed-plugin) for the complete
plugin-authoring guide, runtime usage, and discovery behavior.
