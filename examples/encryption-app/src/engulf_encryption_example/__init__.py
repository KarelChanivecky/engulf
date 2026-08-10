from __future__ import annotations

from engulf import Application

from .goal import EncryptionGoal

application = Application(
    "org.engulf.example.encryption",
    EncryptionGoal(),
    display_name="engulf-encrypt",
)


def main() -> int:
    return application.run()


__all__ = ["application", "main"]
