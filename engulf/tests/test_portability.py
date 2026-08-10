from __future__ import annotations

import importlib
import importlib.abc
import os
import subprocess
import sys
import textwrap
import unittest
from dataclasses import fields

from engulf import StateHomeContext


class PortabilityTestCase(unittest.TestCase):
    def test_state_home_context_has_platform_neutral_identity(self) -> None:
        self.assertEqual(
            tuple(field.name for field in fields(StateHomeContext)),
            ("application_id", "owner_id", "owner_home", "elevated"),
        )

    def test_framework_import_does_not_require_posix_modules(self) -> None:
        script = textwrap.dedent(
            """\
            import importlib.abc
            import sys

            class BlockPosix(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname in {"fcntl", "pwd"}:
                        raise ImportError(f"blocked platform module: {fullname}")
                    return None

            sys.modules.pop("fcntl", None)
            sys.modules.pop("pwd", None)
            sys.meta_path.insert(0, BlockPosix())

            import engulf
            assert engulf.Application is not None
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            text=True,
            capture_output=True,
            env=os.environ.copy(),
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_windows_backend_module_is_safe_to_import(self) -> None:
        module = importlib.import_module("engulf._state_windows")

        self.assertEqual(module.WINDOWS_STATE_PLATFORM.name, "windows")


if __name__ == "__main__":
    unittest.main()
