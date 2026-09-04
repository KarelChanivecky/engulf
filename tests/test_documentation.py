from __future__ import annotations

import ast
import unittest
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
DOCUMENTED_PACKAGES = (
    (
        WORKSPACE / "engulf-api" / "src" / "engulf_api" / "__init__.py",
        WORKSPACE / "engulf-api" / "README.md",
    ),
    (
        WORKSPACE / "engulf" / "src" / "engulf" / "__init__.py",
        WORKSPACE / "engulf" / "README.md",
    ),
    (
        WORKSPACE
        / "engulf-executable-wrapper-api"
        / "src"
        / "engulf_executable_wrapper_api"
        / "__init__.py",
        WORKSPACE / "engulf-executable-wrapper-api" / "README.md",
    ),
    (
        WORKSPACE
        / "engulf-executable-wrapper"
        / "src"
        / "engulf_executable_wrapper"
        / "__init__.py",
        WORKSPACE / "engulf-executable-wrapper" / "README.md",
    ),
    (
        WORKSPACE
        / "plugins"
        / "engulf-plugin-list"
        / "src"
        / "engulf_plugin_list"
        / "__init__.py",
        WORKSPACE / "plugins" / "engulf-plugin-list" / "README.md",
    ),
    (
        WORKSPACE
        / "examples"
        / "encryption-core"
        / "src"
        / "engulf_encryption_example_core"
        / "__init__.py",
        WORKSPACE / "examples" / "encryption-core" / "README.md",
    ),
    (
        WORKSPACE
        / "examples"
        / "encryption-app"
        / "src"
        / "engulf_encryption_example"
        / "__init__.py",
        WORKSPACE / "examples" / "encryption-app" / "README.md",
    ),
)


def _public_exports(path: Path) -> tuple[str, ...]:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for statement in module.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in statement.targets
        ):
            continue
        value = ast.literal_eval(statement.value)
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ):
            raise AssertionError(f"{path} has a nonliteral __all__")
        return tuple(value)
    raise AssertionError(f"{path} does not define __all__")


class DocumentationTestCase(unittest.TestCase):
    def test_package_readmes_name_every_top_level_public_export(self) -> None:
        for package, readme in DOCUMENTED_PACKAGES:
            documentation = readme.read_text(encoding="utf-8")
            missing = tuple(
                name for name in _public_exports(package) if name not in documentation
            )
            with self.subTest(package=package.parent.name):
                self.assertEqual(missing, ())


if __name__ == "__main__":
    unittest.main()
