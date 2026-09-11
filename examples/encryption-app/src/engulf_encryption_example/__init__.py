from __future__ import annotations

import sys

from engulf_encryption_example_core import ENCRYPTION_APPLICATION

from engulf import FRAMEWORK_ERROR_EXIT, GoalPrivilegeError


def main() -> int:
    try:
        with ENCRYPTION_APPLICATION.create() as application:
            return application.run()
    except GoalPrivilegeError as error:
        print(f"engulf-encrypt: {error}", file=sys.stderr)
        return FRAMEWORK_ERROR_EXIT


__all__ = ["ENCRYPTION_APPLICATION", "main"]
