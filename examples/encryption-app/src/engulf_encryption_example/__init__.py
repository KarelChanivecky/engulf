from __future__ import annotations

from engulf_encryption_example_core import ENCRYPTION_APPLICATION


def main() -> int:
    with ENCRYPTION_APPLICATION.create() as application:
        return application.run()


__all__ = ["ENCRYPTION_APPLICATION", "main"]
