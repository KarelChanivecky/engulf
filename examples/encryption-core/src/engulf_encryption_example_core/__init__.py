from __future__ import annotations

from engulf import ApplicationDefinition

from .goal import ENCRYPTION_REQUIREMENT, EncryptionGoal, EncryptionPlugin

ENCRYPTION_APPLICATION = ApplicationDefinition(
    application_id="org.engulf.example.encryption",
    display_name="engulf-encrypt",
    goal_factory=EncryptionGoal,
    vendor="Engulf",
    product="Encryption Example",
    version="0.1.0",
)

__all__ = [
    "ENCRYPTION_APPLICATION",
    "ENCRYPTION_REQUIREMENT",
    "EncryptionGoal",
    "EncryptionPlugin",
]
